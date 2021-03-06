#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Fri Apr 21 19:48:22 2017

@author: leo

Abstract project

METHODS:
    - _gen_id()
    - _path_to(self, data_path, module_name='', file_name='')
    - upload_config_data(self, config_dict, module_name, file_name)
    - read_config_data(self, module_name, file_name)    
    - read_metadata(self)
    - _write_metadata(self)
    - remove(self, module_name='', file_name='')
    - delete_project(self)

# TODO: custom error:
    - Hidden error
    - Return to user

"""

import fcntl
import hashlib
import json
import os
import random
import shutil
import time

from my_json_encoder import MyEncoder

NOT_IMPLEMENTED_MESSAGE = 'NOT IMPLEMENTED in abstract class'

class AbstractProject():

    def __init__(self, 
                     project_id=None, 
                     create_new=False, 
                     description=None,
                     display_name=None,
                     public=False):
        
        if (project_id is None) and (not create_new):
            raise Exception('Set create_new to True or specify project_id')
        if (project_id is not None) and create_new:
            raise Exception('You cannot specify ID for a new project (will be hash)')
            
        if create_new: 
            # Generate project id if none is passed
            self.project_id = self._gen_id()
            
            path_to_proj = self.path_to()
            if os.path.isdir(path_to_proj):
                raise Exception('Project already exists. Choose a new path or \
                                delete the existing: {}'.format(path_to_proj))
            else:
                print(path_to_proj)
                os.makedirs(path_to_proj)
            
            # Create metadata
            self.metadata = self._create_metadata(description=description, 
                                                  display_name=display_name, 
                                                  public=public)
            self._write_metadata()
            
        else:
            self.project_id = project_id
            try:
                self.metadata = self.read_metadata()
            except:
                raise Exception('Project with id {0} could not be loaded'.format(project_id))
        

    def read_full_config(self, exclude_modules=['INIT'], exclude_files=['run_info.json']):
        '''
        Put all json files in a single dictionnary (for export)
        '''
        all_dirs = [x for x in os.listdir(self.path_to()) if os.path.isdir(self.path_to(x))]
        
        full_config = dict()
        
        for module in all_dirs:
            all_json_files = [x for x in os.listdir(self.path_to(module)) \
                if (x[-5:]=='.json') and (x not in exclude_files) and (module not in exclude_modules)]
            for file_name in all_json_files:
                file_path = self.path_to(module, file_name)
                with open(file_path) as f:
                    config = json.load(f)
                    if module not in full_config:
                        full_config[module] = {file_name: config}
                    else:
                        full_config[module][file_name] = config
        return full_config
    
    def upload_full_config(self, full_config):
        '''Writes result of full_config to restore the project'''
        
        for module_name, multi_config in full_config.items():
            for file_name, config in multi_config.items():
                # Create directory if not existent
                dir_path = self.path_to(module_name)
                if not os.path.isdir(dir_path):
                    os.makedirs(dir_path)
                self.upload_config_data(config, module_name, file_name)
      
    @staticmethod
    def _gen_id():
        '''Generate unique non-guessable string for project ID'''
        unique_string = str(time.time()) + '_' + str(random.random())
        h = hashlib.md5()
        h.update(unique_string.encode('utf-8'))
        project_id = h.hexdigest()
        return project_id

    def _create_metadata(self, description=None, display_name=None, public=False):
        '''Core metadatas'''
        metadata = dict()
        metadata['description'] = description
        metadata['display_name'] = display_name
        metadata['public'] = public
        metadata['log'] = {}
        metadata['project_id'] = self.project_id
        metadata['timestamp'] = time.time()
        metadata['last_timestamp'] = metadata['timestamp']
        metadata['user_id'] = '__ NOT IMPLEMENTED'
        return metadata     

    def _path_to(self, data_path, module_name='', file_name=''):
        '''
        Return path to directory that stores specific information for a project 
        module
        '''
        if module_name is None:
            module_name = ''
        if file_name is None:
            file_name = ''
        
        path = os.path.join(data_path, self.project_id, module_name, file_name)
        return os.path.abspath(path)    
        
    def upload_config_data(self, config_dict, module_name, file_name):
        '''Write dict type data with a retry logic if a file is locked.'''
        NUM_RETRY = 10
        RETRY_INTERVAL = 0.1
        
        if config_dict is None:
            return

        # Create directories
        dir_path = self.path_to(module_name)
        if (not os.path.isdir(dir_path)) and module_name:
            os.makedirs(dir_path)   

        file_path = self.path_to(module_name, file_name)

        for _ in range(NUM_RETRY):
            try:
                # Lock File before writing
                with open(file_path, 'a') as f:
                    fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                
                # Write file
                with open(file_path, 'w') as w:
                    json.dump(config_dict, w, cls=MyEncoder)
                
                    # Unlock file
                    fcntl.flock(w, fcntl.LOCK_UN)
                break
                    
            except BlockingIOError:
                time.sleep(RETRY_INTERVAL)
        else:
            raise BlockingIOError('{0} is un-writable because '.format(file_path) \
                                + 'it was locked for by another process')

    def read_config_data(self, module_name, file_name):
        '''Read a json file with retry logic if a file is locked (empty dict 
        if file is not found).
        '''
        NUM_RETRY = 10
        RETRY_INTERVAL = 0.1

        file_path = self.path_to(module_name=module_name, 
                                 file_name=file_name)
        if os.path.isfile(file_path):
            
            for _ in range(NUM_RETRY):
                try:
                    with open(file_path, 'r') as f:
                        # Lock file
                        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        # Read
                        config = json.loads(f.read())
                        # Unlock file
                        fcntl.flock(f, fcntl.LOCK_UN)
                        break
                except BlockingIOError:
                    time.sleep(RETRY_INTERVAL)
            else:
                raise BlockingIOError('{0} is un-readable because '.format(file_path) \
                            + 'it was locked for writing for by another process')
                
        else: 
            config = dict()
        return config               
    

    def _write_metadata(self):
        self.metadata['last_timestamp'] = time.time()
        self.upload_config_data(self.metadata, 
                                module_name='', 
                                file_name='metadata.json')

    def read_metadata(self):
        '''Wrapper around read_config_data'''
        metadata = self.read_config_data(module_name='', file_name='metadata.json')
        assert metadata['project_id'] == self.project_id
        return metadata
    
    def _remove(self, module_name='', file_name=''):
        '''Removes a file from the project'''
        file_path = self.path_to(module_name, file_name)
        
        if os.path.isfile(file_path):
            os.remove(file_path)
        else:
            raise FileNotFoundError('{0} (in: {1}) could not be found in \
                            project'.format(file_name, module_name))

    def delete_project(self):
        '''Deletes entire folder containing the project'''
        path_to_proj = self.path_to()
        shutil.rmtree(path_to_proj)
    


