#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Mon Feb  6 15:01:16 2017

@author: leo

TODO:
    - Safe file name / not unique per date
    
    - API: List of internal referentials
    - API: List of finished modules for given project / source
    - API: List of loaded sources
    
    - API: Fetch logs
    - API: Move implicit load out of API
    
    - API: Error codes / remove error
    
    - Use logging module
    
    - Change metadata to use_internal and ref_name to last used or smt. Data to
      use is specified on api call and not read from metadata (unless using last used)
    
    - Protect admin functions

    - General error handling
    
    
    - ABSOLUTELY:  handle memory issues
    - Allocate memory by user/ by IP?
    
    - Study impact of training set size on match rate

    - Choose btw add/select/upload and read/load/get
    
    - Catch exceptions. 
    
    - Re-Run inference if selecting more columns

    - Dealing with inference parameters when columns change...

    - integration test
    
    - Error if job failed
    
    - Avoid import in scheduled 
    - fix cancel job
    
    - DEPRECATE restriction with (done in elasticsearch)
    
    - delete index with project

    - https://blog.miguelgrinberg.com/post/restful-authentication-with-flask

DEV GUIDELINES:
    - By default the API will use the file with the same name in the last 
      module that was completed. Otherwise, you can specify the module to use file from
    - Suggestion methods shall be prefixed by infer (ex: infer_load_params, infer_mvs)
    - Suggestion methods shall can be plugged as input as params variable of transformation modules
    - Single file modules shall take as input: (pandas_dataframe, params)
    - Single file modules suggestion modules shall ouput (params, log)
    - Single file modules replacement modules shall ouput (pandas_dataframe, log)
    
    - Multiple file modules shall take as input: (pd_dataframe_1, pd_dataframe_2, params)
    - Multiple file modules suggestion modules shall ouput params, log
    - Multiple file modules merge module shall ouput ???
    
    - run_info should contain fields: has_modifications and modified_columns
    
    - Files generated by modules should be in module directory and have names determined at the project level (not API, nor module)
    
    - Do NOT return files, instead write files which users can fetch file through the API
    - If bad params are passed to modules, exceptions are raised, it is the 
        APIs role to transform these exceptions in messages
    - Functions to check parameters should be named _check_{variable_or_function} (ex: _check_file_role)
    - All securing will be done in the API part
    - Always return {"error": ..., "project_id": ..., "response": ...} ???

    - All methods to load specific configs should raise an error if the config is not coherent
    - For each module, store user input
    
    - Load all configurations to project variables
    
    - Use _init_project when project_type is a variable in path
    
    - Always include project_type as variable or hardcode
    - Put module name before project_type if it exists for all project_type
    - Put module name after project_type if it exists only for this project_type (only with linker)
    - Put in API code modules that are of use only for the API

NOTES:
    - Pay for persistant storage?

# Download metadata
curl -i http://127.0.0.1:5000/metadata/ -X POST -F "request_json=@sample_download_request.json;type=application/json"

USES: /python-memcached
"""

import gzip
import json
import logging
import os
import shutil
import tempfile
    
# Change current path to path of api.py
curdir = os.path.dirname(os.path.realpath(__file__))
os.chdir(curdir)

# Flask imports
import flask
from flask import Flask, jsonify, render_template, request, send_file, url_for
from flask_session import Session
from flask_socketio import disconnect, emit, SocketIO
from flask_cors import CORS, cross_origin
import werkzeug
from werkzeug.utils import secure_filename

# Redis imports
from rq import cancel_job as rq_cancel_job, Queue
from rq.job import Job
from worker import conn, VALID_QUEUES

import api_queued_modules

from admin import Admin
from my_json_encoder import MyEncoder
from normalizer import ESReferential, UserNormalizer, MINI_PREFIX
from linker import UserLinker

#==============================================================================
# INITIATE APPLICATION
#==============================================================================

# Initiate application
app = Flask(__name__)
app.json_encoder = MyEncoder

cors = CORS(app)    
app.config['CORS_HEADERS'] = 'Content-Type'
#app.config['SERVER_NAME'] = '127.0.0.1:5000'
app.config['SESSION_TYPE'] = "memcached"# 'memcached'

Session(app)

app.debug = True
app.config['SECRET_KEY'] = open('secret_key.txt').read()
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024 * 1024 # Check that files are not too big (10GB)
app.config['ALLOWED_EXTENSIONS'] = ['csv', 'xls', 'xlsx', 'zip']

socketio = SocketIO(app)       

# Redis connection
q = dict()
for q_name in VALID_QUEUES:
    q[q_name] = Queue(q_name, connection=conn, default_timeout=1800)

#==============================================================================
# HELPER FUNCTIONS
#==============================================================================
    
def _check_privilege(privilege):
    if privilege not in ['user', 'admin']:
        raise Exception('privilege can be only user or admin')

def _check_project_type(project_type):
    if project_type not in ['normalize', 'link']:
        raise Exception('project type can be only normalize or link')

def _check_file_role(file_role):
    if file_role not in ['ref', 'source']:
        raise Exception('File type should be ref or source')

def _check_request():
    '''Check that input request is valid'''
    pass

def _parse_request():
    '''
    Separates data information from parameters and assures that values in data
    parameters are safe
    '''
    # Parse json request
    data_params = None
    module_params = None
    if request.json:
        req = request.json
        assert isinstance(req, dict)
    
        if 'data_params' in req:
            data_params = req['data_params']
            
            # Make paths secure
            for key, value in data_params.items():
                data_params[key] = secure_filename(value)
            
        if 'module_params' in req:
            module_params = req['module_params']
    
    return data_params, module_params
    
def _parse_linking_request():
    data_params = None
    module_params = None
    if request.json:
        params = request.json
        assert isinstance(params, dict)
    
        if 'data_params' in params:
            data_params = params['data_params']
            for file_role in ['ref', 'source']:
                # Make paths secure
                for key, value in data_params[file_role].items():
                    data_params[file_role][key] = secure_filename(value)
                
        if 'module_params' in params:
            module_params = params['module_params']
    
    return data_params, module_params    


def _init_project(project_type, 
                 project_id=None, 
                 create_new=False, 
                 display_name=None, 
                 description=None):
    '''
    Runs the appropriate constructor for Linker or Normalizer projects
    
    DEV NOTE: Use this in api calls that have project_type as a variable
    '''
    _check_project_type(project_type)
    
    if project_type == 'link':
        proj = UserLinker(project_id=project_id, 
                          create_new=create_new, 
                          display_name=display_name, 
                          description=description)
    else:
        proj = UserNormalizer(project_id=project_id, 
                              create_new=create_new, 
                              display_name=display_name, 
                              description=description)
    return proj
            


#==============================================================================
# Error handling
#==============================================================================


@app.errorhandler(404)
def page_not_found(error):
    app.logger.error('URL not valid: %s', (error))
    return jsonify(error=True, message=error.description), 404

@app.errorhandler(405)
def method_not_allowed(error):
    app.logger.error('Method not allowed (POST or GET): %s', (error))
    return jsonify(error=True, message=error.description), 404


#==============================================================================
# API
#==============================================================================

# TODO: get_config if module_name is specified specific module, otherwise, entire project
#@app.route('/api/<project_type>/<project_id>/<module_name>/<file_name>/')
#def get_config(project_type, project_id, module_name=None, file_name=None):
#    '''See docs in abstract_project'''
#    proj = _init_project(project_type, project_id)
#    return proj.get_config(module_name, file_name)

#==============================================================================
# GENERIC API METHODS (NORMALIZE AND LINK)
#==============================================================================

@app.route('/api/new/<project_type>', methods=['POST'])
def new_project(project_type):
    '''
    Create a new project:
        
    GET:
        - project_type: "link" or "normalize"
        
    POST:
        - (description): project description
        - (display_name): name to show to user
        - (internal): (synonymous to public)
    
    '''
    _check_project_type(project_type)
    
    # TODO: include internal in form somewhere
    description = request.json.get('description', '')
    display_name = request.json.get('display_name', '')
    internal = request.json.get('internal', False)
    
    if internal and (not description):
        raise Exception('Internal projects should have a description')

    if project_type == 'normalize':
        proj = UserNormalizer(create_new=True, description=description, display_name=display_name)
    else:
        proj = UserLinker(create_new=True, description=description, display_name=display_name)

    
    return jsonify(error=False, 
                   project_id=proj.project_id)

@app.route('/api/delete/<project_type>/<project_id>', methods=['GET'])
def delete_project(project_type, project_id):
    """
    Delete an existing project (including all configuration, data and metadata)
    
    GET:
        - project_type: "link" or "normalize"
        - project_id
    """
    _check_project_type(project_type)
    # TODO: replace by _init_project
    if project_type == 'normalize':
        proj = ESReferential(project_id=project_id)
    else:
        proj = UserLinker(project_id=project_id)
    proj.delete_project()
    return jsonify(error=False)


@app.route('/api/metadata/<project_type>/<project_id>', methods=['GET'])
@cross_origin()
def metadata(project_type, project_id):
    '''
    Fetch metadata for project ID
    
    GET:
        - project_type: "link" or "normalize"
        - project_id
    '''
    proj = _init_project(project_type, project_id=project_id)
    resp = jsonify(error=False,
                   metadata=proj.metadata, 
                   project_id=proj.project_id)
    return resp


def set_skipped(project_type, project_id):
    """
    Set skip value for selected module
    
    GET:
        - project_type: "link" or "normalize"
        - project_type
        
    POST:
        data_params:
            - file_name
        module_params:
            - module_name
            - skip_value: (true)
    """
    data_params, module_params = _parse_request()
    
    proj = _init_project(project_type, project_id)
    proj.set_skip(module_params['module_name'], data_params['file_name'], 
                  module_params.get('skip_value', True))


@app.route('/api/last_written/<project_type>/<project_id>', methods=['GET', 'POST'])
def get_last_written(project_type, project_id):
    """
    Get coordinates (module_name, file_name) of the last file written for a 
    given project.
    
    wrapper around: AbstractDataProject.get_last_written
    
    GET:
        - project_type: "link" or "normalize"
        - project_id
    POST:
        - module_name: if not null, get last file written in chosen module
        - file_name: if not null, get last file written with this given_name
        - before_module: (contains module_name) if not null, get coordinates 
                            for file written before the chosen module (with an 
                            order specified by MODULE_ORDER)
    """
    proj = _init_project(project_type, project_id)
    (module_name, file_name) = proj.get_last_written(request.json.get('module_name'), 
                          request.json.get('file_name'), 
                          request.json.get('before_module'))
    return jsonify(project_type=project_type, 
                   project_id=project_id, 
                   module_name=module_name, 
                   file_name=file_name)


@app.route('/api/download/<project_type>/<project_id>', methods=['GET', 'POST'])
@cross_origin()
def download(project_type, project_id):
    '''
    Download specific file from project.
    
    GET:
        - project_type: "link" or "normalize"
        - project_type
        
    POST:
        data_params:
            - module_name: Module from which to fetch the file
            - file_name
        module_params:
            - file_type: ['csv' or 'xls']
    
    '''
    project_id = secure_filename(project_id)

    proj = _init_project(project_type, project_id)
    data_params, module_params = _parse_request()
    
    if data_params is None:
        data_params = {}
        
    file_role = data_params.get('file_role')
    module_name = data_params.get('module_name')
    file_name = data_params.get('file_name')

    if file_role is not None:
        file_role = secure_filename(file_role)
    if module_name is not None:
        module_name = secure_filename(module_name)
    if file_name is not None:
        file_name = secure_filename(file_name)
        
    
    if module_params is None:
        file_type = 'csv'
    else:
        file_type = module_params.get('file_type', 'csv')
    
    if file_type not in ['csv', 'xls', 'xlsx']:
        raise ValueError('Download file type should be csv, xls or xlsx')
        
        

    (module_name, file_name) = proj.get_last_written(module_name, file_name)

    if module_name == 'INIT':
        return jsonify(error=True,
               message='No changes were made since upload. Download is not \
                       permitted. Please do not use this service for storage')
        
    if file_type == 'csv':
        new_file_name = file_name.split('.csv')[0] + '_MMM.csv'
    else:
        new_file_name = proj.to_xls(module_name, file_name)
    
    file_path = proj.path_to(module_name, file_name)

    # Zip this file and send the zipped file
    zip_file_name = new_file_name + '.zip'
    zip_file_path = proj.path_to(module_name, zip_file_name)
    with open(file_path, 'rb') as f_in, gzip.open(zip_file_path, 'wb') as f_out:
        shutil.copyfileobj(f_in, f_out)        
    
    return send_file(zip_file_path, as_attachment=True, attachment_filename=zip_file_name)


# TODO: get this from MODULES ?
API_SAMPLE_NAMES = ['standard', 'sample_mvs', 'sample_types']

@app.route('/api/sample/<project_type>/<project_id>', methods=['POST'])
@cross_origin()
def get_sample(project_type, project_id):
    '''
    Generate a sample.
    
    GET:
        - project_type
        - project_id
        
    POST:
        - data_params:
            - module_name
            - file_name
        - module_params:
            - sampler_module_name: (ex: 'sample_mvs'). 
                            TODO: explicit
            - module_params: (optional) parameters generated by the associated inference module 
                            (Usually the result of inference. ex: result of infer_mvs)
            - sample_params: (optional) parameters to use for sampling 
                            TODO: standardize and explicit
                            {
                            'restrict_to_selected': True or False (default True),
                            'num_rows': number of rows to return (default 50) (does not apply for non standard samplers)
                            'randomize': (default True) If false, will return first values
                            }
    '''
    proj = _init_project(project_type=project_type, project_id=project_id)    
    data_params, all_params = _parse_request() # TODO: add size limit on params
    
    if all_params is None:
        all_params = dict()

    sampler_module_name = all_params.get('sampler_module_name', None)
    if sampler_module_name == 'standard':
        sampler_module_name = None
    
    module_params = all_params.get('module_params', {})
    sample_params = all_params.get('sample_params', {})
    sample_params.setdefault('restrict_to_selected', True)

    # Get sample
    proj.load_data(data_params['module_name'], 
                   data_params['file_name'], 
                   restrict_to_selected=sample_params['restrict_to_selected'])

    sample_params.setdefault('randomize', True)
    sample_params.setdefault('num_rows', 50) # TODO: figure out how to put back min(50, proj.mem_data.shape[0]))

    if (sampler_module_name is not None) and (sampler_module_name not in API_SAMPLE_NAMES):
        raise ValueError('Requested sampler_module_name {0} is not valid. Valid'\
                         + 'modules are: {1}'.format(sampler_module_name, API_SAMPLE_NAMES))
        
    sample = proj.get_sample(sampler_module_name, module_params, sample_params)
    return jsonify(sample=sample)


@app.route('/api/exists/<project_type>/<project_id>', methods=['GET'])
@cross_origin()
def project_exists(project_type, project_id):
    '''
    Check if project exists
    
    GET:
        - project_type: "link" or "normalize"
        - project_id
    '''
    try:
        _init_project(project_type=project_type, project_id=project_id)
        return jsonify(exists=True)
    except Exception as exc: 
        return jsonify(exists=False)

@app.route('/api/download_config/<project_type>/<project_id>/', methods=['POST'])
@cross_origin()
def read_config(project_type, project_id):
    """
    Reads content of a config file
    
    GET:
        - project_type: "link" or "normalize"
        - project_id
        
    POST:
        - data: {
                "module_name": module to fetch from
                "file_name": file to fetch
                }    
    """
    # TODO: do not expose ?
    proj = _init_project(project_type=project_type, project_id=project_id)    
    data_params, _ = _parse_request() # TODO: add size limit on params
    
    file_name = data_params['file_name']
    
    # Check that the file_name is allowed:
    assert (file_name in ['training.json', 'infered_config.json', 'config.json',
                          'column_matches.json']) \
            or '__run_info.json' in file_name
    
    result = proj.read_config_data(data_params['module_name'], file_name)
    return jsonify(result=result)



@app.route('/api/upload_config/<project_type>/<project_id>/', methods=['POST'])
@cross_origin()
def upload_config(project_type, project_id):
    """
    Writes the content of params
    
    GET:
        - project_type: "link" or "normalize"
        - project_id
        
    POST:
        - data_params: {
                "module_name": module to fetch from
                "file_name": file to fetch
                }
        - module_params: parameters to write
    """
    # TODO: do not expose ?
    proj = _init_project(project_type=project_type, project_id=project_id)    
    data_params, params = _parse_request() # TODO: add size limit on params
    
    file_name = data_params['file_name']
    
    # Check that the file_name is allowed:
    assert file_name in ['training.json', 'config.json', 'learned_settings.json']
    
    proj.upload_config_data(params, data_params['module_name'], file_name)
    return jsonify(error=False)

#==============================================================================
# NORMALIZE API METHODS (see also SCHEDULER)
#==============================================================================

@app.route('/api/normalize/select_columns/<project_id>', methods=['POST'])
def add_selected_columns(project_id):
    """
    Select columns to modify in normalization project. 
    
    /!\ If column selection includes new columns 
    
    GET:
        - project_id

    POST: 
        - columns: [list of columns]
        
    """
    selected_columns = request.json['columns']
    proj = UserNormalizer(project_id=project_id)
    proj.add_selected_columns(selected_columns)    
    return jsonify(error=False)

@app.route('/api/normalize/upload/<project_id>', methods=['POST'])
@cross_origin()
def upload(project_id):
    '''
    Uploads files to a normalization project. (NB: cannot upload directly to 
    a link type project). 
                                               
    Also creates the mini version of the project
    
    GET:
        - project_id: ID of the normalization project
        
    POST:
        
      file: (csv file) A csv to upload to the chosen normalization project
                  NB: the "filename" property will be used to name the file
      json:
        - module_params:
            - make_mini: (default True) Set to False to NOT create a mini version of the file
            - sample_size
            - randomize
    '''
    # Load project
    proj = UserNormalizer(project_id=project_id) 
    _, module_params = _parse_request()   
    if module_params is None:
        module_params = {}
    make_mini = module_params.get('make_mini', True)
    
    # Upload data        
    def custom_stream_factory(total_content_length, filename, content_type, content_length=None):
        tmpfile = tempfile.NamedTemporaryFile('wb+', prefix='flaskapp')
        app.logger.info("start receiving file ... filename => " + str(tmpfile.name))
        return tmpfile
    
    _, _, files = werkzeug.formparser.parse_form_data(flask.request.environ, stream_factory=custom_stream_factory)
    
    
    # Upload data
    file_name = files['file'].filename
    stream = files['file'].stream
    
    _, run_info = proj.upload_init_data(stream, file_name)
    
    # Make mini
    if make_mini:
        proj.load_data('INIT', run_info['file_name'])
        proj.make_mini(module_params)
        
        # Write transformations and log # TODO: not clean
        if proj.metadata['has_mini']:
            proj.write_data()
        else:
            proj.write_metadata()

    return jsonify(run_info=run_info, project_id=proj.project_id)


#@app.route("/upload/<filename>", methods=["POST", "PUT"])
#def upload_process(filename):
#    filename = secure_filename(filename)
#    fileFullPath = os.path.join(application.config['UPLOAD_FOLDER'], filename)
#    with open(fileFullPath, "wb") as f:
#        chunk_size = 4096
#        while True:
#            chunk = flask.request.stream.read(chunk_size)
#            if len(chunk) == 0:
#                return
#
#            f.write(chunk)
#    return jsonify({'filename': filename})


@app.route('/api/normalize/make_mini/<project_id>', methods=['POST'])
@cross_origin()
def make_mini(project_id):
    '''
    Create sample version of selected file (call just after upload).
    
    GET:
        - project_id
    POST:
        - data_params: 
                        {
                        module_name: 'INIT' (mandatory to be init)
                        file_name: 
                        }
        - module_params: {
                            sample_size: 
                            randomize:
                        }
    '''
    data_params, module_params = _parse_request()   
    proj = UserNormalizer(project_id=project_id)
    
    proj.load_data(data_params['module_name'], data_params['file_name'])
    proj.make_mini(module_params)
    
    # Write transformations and log
    proj.write_data()


#==============================================================================
# LINK API METHODS (see also SCHEDULER)
#==============================================================================

@app.route('/api/link/select_file/<project_id>', methods=['POST'])
def select_file(project_id):
    '''    
    TODO: FIX THIS MESS  !!!!
    
    Choose a file to use as source or referential for merging
    send {file_role: "source", project_id: "ABCYOUANDME", internal: False}
    
    GET:
        - project_id: ID for the "link" project
        
    POST:
        - file_role: "ref" or "source". Role of the normalized file for linking
        - project_id: ID of the "normalize" project to use for linking
    '''
    proj = UserLinker(project_id)
    params = request.json
    proj.add_selected_project(file_role=params['file_role'], 
                           internal=params.get('internal', False), # TODO: remove internal
                           project_id=params['project_id'])
    return jsonify(error=False)


@app.route('/api/link/add_column_matches/<project_id>/', methods=['POST'])
@cross_origin()
def add_column_matches(project_id):
    """
    Add pairs of columns to compare for linking.
    
    wrapper around UserLinker.add_col_matches
    
    GET: 
        - project_id: ID for the "link" project
        
    POST:
        - column_matches: [list object] column matches (see doc in original function)
    """
    column_matches = request.json['column_matches']
    proj = UserLinker(project_id=project_id)
    proj.add_col_matches(column_matches)
    return jsonify(error=False)
    

@app.route('/api/link/add_column_certain_matches/<project_id>/', methods=['POST'])
@cross_origin()
def add_column_certain_matches(project_id):
    '''
    Specify certain column matches (exact match on a subset of columns equivalent 
    to entity identity). This is used to test performances.
    
    wrapper around UserLinker.add_col_certain_matches
    
    GET:
        - project_id: ID for "link" project
        
    POST:
        - column_certain_matches: {dict object}: (see doc in original function)
    
    '''
    column_matches = request.json['column_certain_matches']
    proj = UserLinker(project_id=project_id)
    proj.add_col_certain_matches(column_matches)
    return jsonify(error=False)



@app.route('/api/link/add_columns_to_return/<project_id>/<file_role>/', methods=['POST'])
@cross_origin()
def add_columns_to_return(project_id, file_role):
    '''
    Specify columns to be included in download version of file. For link project 
    
    # TODO: shouldn't this be for normalize also ?
    
    wrapper around UserLinker.add_cols_to_return
    
    GET:
        project_id: ID for "link" project
        file_role: "ref" or "source"
    '''
    columns_to_return = request.json
    proj = UserLinker(project_id=project_id)
    proj.add_cols_to_return(file_role, columns_to_return)    
    return jsonify(error=False)


# =============================================================================
# Socket methods
# =============================================================================
    
@socketio.on('load_labeller', namespace='/')
def load_labeller(message_received):
    '''Loads labeller. Necessary to have a separate call to preload page'''
    message_received = json.loads(message_received)
    project_id = message_received['project_id']
    
    # TODO: put variables in memory
    # TODO: remove from memory at the end
    proj = UserLinker(project_id=project_id)
    paths = proj._gen_paths_es() 
    
    # Create flask labeller memory if necessary and add current labeller
    try:
        flask._app_ctx_stack.labeller_mem[project_id] = dict()
    except:
        flask._app_ctx_stack.labeller_mem = {project_id: dict()}
    
    # Generate dedupe paths and create labeller
    flask._app_ctx_stack.labeller_mem[project_id]['paths'] = paths
    flask._app_ctx_stack.labeller_mem[project_id]['labeller'] = proj._read_labeller('es_linker')
    
    flask._app_ctx_stack.labeller_mem[project_id]['labeller'].new_label()
    
    encoder = MyEncoder()
    emit('message', encoder.encode(flask._app_ctx_stack.labeller_mem[project_id]['labeller'].to_emit(message='')))

    
@socketio.on('answer', namespace='/')
def web_get_answer(message_received):
    # TODO: avoid multiple click (front)
    # TODO: add safeguards  if not enough train (front)

    message_received = json.loads(message_received)
    logging.info(message_received)
    project_id = message_received['project_id']
    user_input = message_received['user_input']
    
    
    message_to_display = ''
    #message = 'Expect to have about 50% of good proposals in this phase. The more you label, the better...'
    if flask._app_ctx_stack.labeller_mem[project_id]['labeller'].answer_is_valid(user_input):
        flask._app_ctx_stack.labeller_mem[project_id]['labeller'].parse_valid_answer(user_input)
        if flask._app_ctx_stack.labeller_mem[project_id]['labeller'].finished:
            logging.info('Writing train')
            flask._app_ctx_stack.labeller_mem[project_id]['labeller'].write_training(flask._app_ctx_stack.labeller_mem[project_id]['paths']['train'])
            logging.info('Wrote train')
            
            try:
                del flask._app_ctx_stack.labeller_mem[project_id]['labeller']
                logging.info('Deleted labeller for project: {0}'.format(project_id))
            except:
                logging.warning('Could not delete labeller for project: {0}'.format(project_id))
            try:
                del flask._app_ctx_stack.labeller_mem[project_id]['paths']
            except:
                logging.warning('Could not delete paths for project: {0}'.format(project_id))
            
        else:
            flask._app_ctx_stack.labeller_mem[project_id]['labeller'].new_label()
    else:
        message_to_display = 'Sent an invalid answer'
    emit('message', flask._app_ctx_stack.labeller_mem[project_id]['labeller'].to_emit(message=message_to_display))
    

@socketio.on('terminate', namespace='/')
def web_terminate_labeller_load(message_received):
    '''Clear memory in application for selected project'''
    message_received = json.loads(message_received)
    project_id = message_received['project_id']
    
    try:
        del flask._app_ctx_stack.labeller_mem[project_id]['labeller']
        logging.info('Deleted labeller for project: {0}'.format(project_id))
    except:
        logging.warning('Could not delete labeller for project: {0}'.format(project_id))
    try:
        del flask._app_ctx_stack.labeller_mem[project_id]['paths']
    except:
        logging.warning('Could not delete paths for project: {0}'.format(project_id))
            


#==============================================================================
# SCHEDULER
#==============================================================================

# TODO: job_id does not allow to call all steps of a pipeline at once
# TODO: put all job schedulers in single api (assert to show possible methods) or use @job   

## TODO: get this from MODULES ?
#API_MODULE_NAMES = ['infer_mvs', 'replace_mvs', 'infer_types', 'recode_types', 
#                    'concat_with_init', 'run_all_transforms', 'create_labeller', 
#                    'infer_restriction', 'perform_restriction',
#                    'linker', 'link_results_analyzer']

SCHEDULED_JOBS = {
                    'infer_mvs': {'project_type': 'normalize'}, 
                    'replace_mvs': {'project_type': 'normalize'}, 
                    'infer_types': {'project_type': 'normalize'}, 
                    'recode_types': {'project_type': 'normalize'}, 
                    'concat_with_init': {'project_type': 'normalize'}, 
                    'run_all_transforms': {'project_type': 'normalize'}, 
                    'create_es_index': {'project_type': 'link'},
                    'create_es_labeller': {'project_type': 'link', 
                                        'priority': 'high'}, 
                    'es_linker': {'project_type': 'link'},
                    'infer_restriction': {'project_type': 'link', 
                                          'priority': 'high'}, 
                    'perform_restriction': {'project_type': 'link'},
                    'linker': {'project_type': 'link'}, 
                    'link_results_analyzer': {'project_type': 'link'}
                    }

def choose_queue(job_name, project_id, data_params):
    '''
    Priority is low by default. It is high if specified in SCHEDULED_MODULES
    or if performing on a __MINI or file that doesn't have __MINI
    # TODO: MAKE impossible to overwrite metadata
    '''
    project_type = SCHEDULED_JOBS[job_name]['project_type']
    proj = _init_project(project_type=project_type, project_id=project_id)  

    if data_params and data_params is not None:
        if (project_type=='normalize') and (
                    (MINI_PREFIX in data_params['file_name']) 
                    or (not proj.metadata['has_mini'])):
            return 'high'
    
    return SCHEDULED_JOBS[job_name].get('priority', 'low')
    

@app.route('/api/schedule/<job_name>/<project_id>/', methods=['GET', 'POST'])
@cross_origin()
def schedule_job(job_name, project_id):    
    '''
    Schedule module runs
    
    GET:
        - job_name: name of module to run (full list in API_MODULE_NAMES)
        - project_id
    POST:
    
        - data_params: the data to transform (see specific module docs)
        - module_params: how to transform the data (see spectific module docs)
    
    ex: '/api/schedule/infer_mvs/<project_id>/'
    '''
    assert job_name in SCHEDULED_JOBS
    data_params, module_params = _parse_request()

    q_priority = choose_queue(job_name, project_id, data_params)
    assert q_priority in VALID_QUEUES
    
    job_id = project_id + '_' + job_name
    #TODO: remove and de-comment unfer
    job = q[q_priority].enqueue_call(
            func='api_queued_modules._' + job_name,
            args=(project_id, data_params, module_params), 
            result_ttl=5000, 
            job_id=job_id, 
            #depends_on=project_id
    )        
    
    # 
    job_id = job.get_id()
    logging.info('Scheduled job: {0}'.format(job_id))
    return jsonify(job_id=job_id,
                   job_result_api_url=url_for('get_job_result', job_id=job_id))    
    

@app.route('/queue/result/<job_id>', methods=['GET'])
def get_job_result(job_id):
    '''
    Fetch the json output of a module run scheduled by schedule_job. Will return 
    a 202 code if job is not yet complete and 404 if job could not be found.
    
    GET:
        - job_id: as returned by schedule_job
    '''    
    try:
        job = Job.fetch(job_id, connection=conn)
    except:
        return jsonify(error=True, message='job_id could not be found', completed=False), 404
        
    if job.status == 'failed':
        return jsonify(error=True, message='Job failed', completed=False), 500
    
    if job.is_finished:
        #return str(job.result), 200
        return jsonify(completed=True, result=job.result)
    else:
        if job.status == 'failed':
            return jsonify(completed=False, error=True, message=job.exc_info), 500
        
        # TODO: Check for success specifically
        return jsonify(completed=False), 202

@app.route('/queue/cancel/<job_id>', methods=['GET'])
def cancel_job(job_id):
    '''
    Remove job from queue
    
    
    
    # TODO: make this work
    
    GET:
        - job_id: as returned by schedule_job
    '''
    
    try:
        job = Job.fetch(job_id, connection=conn)
        job.cancel()
        return jsonify(job_canceled=True, completed=False)
    except:
        return jsonify(job_canceled=False,
                       error=True, 
                       message='job_id could not be found', 
                       completed=False), 404
    



@app.route('/queue/num_jobs/<job_id>', methods=['GET'])
def count_jobs_in_queue_before(job_id):
    '''
    Returns the number of jobs preceding job_id or -1 if job is no longer in queue.
    
    GET:
        - job_id: as returned by schedule_job
    
    '''
    job_ids = q.job_ids
    if job_id in job_ids:
        return jsonify(num_jobs=job_ids.index(job_id))
    else:
        return jsonify(num_jobs=-1)
    # TODO: check if better to return error
    
@app.route('/queue/num_jobs/', methods=['GET'])
def count_jobs_in_queue():
    '''Returns the number of jobs enqueued'''
    # TODO: change for position in queue
    num_jobs = len(q.job_ids)
    return jsonify(num_jobs=num_jobs)

#==============================================================================
    # Admin
#==============================================================================

@app.route('/api/projects/<project_type>', methods=['GET'])
def list_projects(project_type):
    '''
    TODO: TEMPORARY !! DELETE FOR PROD !!!
    '''
    admin = Admin()
    list_of_projects = admin.list_project_ids(project_type)
    return jsonify(list_of_projects)



if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)
