#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Fri Feb 24 14:04:51 2017

@author: leo




"""
import os
import time

from project import MODULES, Project
from referential import Referential

from CONFIG import DATA_PATH

class UserProject(Project):
    """
    This class provides tools to manage user projects
    """
    def check_file_role(self, file_role):
        if (file_role not in ['ref', 'source', 'link']) and (file_role is not None):
            raise Exception('"file_role" is either "source" or "ref"')
    
    def path_to(self, file_role='', module_name='', file_name=''):
        '''
        Return path to directory that stores specific information for a project 
        module
        '''
        if file_role is None:
            file_role = ''
        if module_name is None:
            module_name = ''
        if file_name is None:
            file_name = ''
            
        if file_role:
            self.check_file_role(file_role)
        try:
            path = os.path.join(DATA_PATH, 'projects', self.project_id, file_role, 
                                module_name, file_name)
        except:
            import pdb
            pdb.set_trace()
        return os.path.abspath(path)    

    def create_metadata(self):
        metadata = dict()
        metadata['timestamp'] = time.time()
        metadata['user_id'] = 'NOT IMPlEMENTED'
        metadata['use_internal_ref'] = None
        metadata['ref_name'] = None
        #metadata['source_names'] = []
        metadata['log'] = []
        metadata['project_id'] = self.project_id
        return metadata   


    def linker(self, module_name, paths, params):
        '''
        # TODO: This is not optimal. Find way to change paths to smt else
        '''
        
        # Add module-specific paths
        if module_name ==  'dedupe_linker':
            assert 'train_path' not in paths
            assert 'learned_settings_path' not in paths
            
            paths['train'] = self.path_to('link', module_name, 'training.json')
            paths['learned_settings'] = self.path_to('link', module_name, 'learned_settings')
        
        # Initiate log
        log = self.init_log(module_name, 'link')

        self.mem_data, thresh = MODULES['link'][module_name](paths, params)
        
        self.mem_data_info['module'] = module_name
        self.mem_data_info['file_role'] = 'link'
        self.mem_data_info['file_name'] = 'mmm_result.csv'
        
        # Complete log
        log = self.end_log(log, error=False)
                          
        # Update log buffer
        self.log_buffer.append(log)
        
        return 




if __name__ == '__main__':
    # Create/Load a project
    project_id = "4e8286f034eef40e89dd99ebe6d87f21"
    proj = UserProject(None, create_new=True)
    
    # Upload source to project
    file_names = ['source.csv']
    for file_name in file_names:
        file_path = os.path.join('local_test_data', file_name)
        with open(file_path) as f:
            proj.add_init_data(f, 'source', file_name)

    # Upload ref to project
    file_path = 'local_test_data/ref.csv'
    with open(file_path) as f:
        proj.add_init_data(f, 'ref', file_name)

    # Load source data to memory
    proj.load_data(file_role='source', module_name='INIT' , file_name='source.csv')
    
    infered_params = proj.infer('infer_mvs', None)
    
    # Try transformation
    params = {'mvs_dict': {'all': [],
              'columns': [{'col_name': u'uai',
                           'missing_vals': [{'origin': ['len_ratio'],
                                             'score': 0.2,
                                             'val': u'NR'}]}]},
                'thresh': 0.6}
    proj.transform('replace_mvs', params)
    
    # Write transformed file
    proj.write_data()
    proj.write_log_buffer(written=True)
    
    # Remove previously uploaded file
    # proj.remove_data('source', 'INIT', 'source.csv')    

    
    
    # Try deduping
    paths = dict()
    
    (file_role, module_name, file_name) = proj.get_last_written(file_role='ref')
    paths['ref'] = proj.path_to(file_role, module_name, file_name)
    
    (file_role, module_name, file_name) = proj.get_last_written(file_role='source')
    paths['source'] = proj.path_to(file_role, module_name, file_name)
    
    ## Parameters
    # Variables
    my_variable_definition = [
                            {'field': 
                                    {'source': 'lycees_sources',
                                    'ref': 'full_name'}, 
                            'type': 'String', 
                            'crf':True, 
                            'missing_values':True},
                            
                            {'field': {'source': 'commune', 
                                       'ref': 'localite_acheminement_uai'}, 
                            'type': 'String', 
                            'crf': True, 
                            'missing_values':True}
                            ]

    # What columns in reference to include in output
    selected_columns_from_ref = ['numero_uai', 'patronyme_uai', 
                                 'localite_acheminement_uai']
    
    #                          
    params = {'variable_definition': my_variable_definition,
              'selected_columns_from_ref': selected_columns_from_ref}

    # Add training data
    with open('local_test_data/training.json') as file:
        proj.add_config_data(file, 'link', 'dedupe_linker', 'training.json')                 
              
              
    proj.linker('dedupe_linker', paths, params)
    proj.write_data()
    proj.write_log_buffer(written=True)
    
    
    
    import pprint
    pprint.pprint(proj.get_arb())
    pprint.pprint(proj.metadata)
    
    pprint.pprint(proj.log_by_file_name())
        