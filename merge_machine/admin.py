#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Fri Mar  3 10:37:58 2017

@author: leo
"""

import os
import shutil

from user_project import UserProject

from CONFIG import DATA_PATH

class Admin():
    def __init__(self):
        self.project_ids = self.list_projects()
        self.internal_refs = self.list_referentials()
    
    def path_to(self, content, project_id=''):
        '''Returns path to directory containing projects or referentials'''
        if content not in ['referentials', 'projects']:
            raise Exception('Admin path_to accepts only `referential` or projects')
        if project_id and (content == 'referentials'):
            raise Exception('project_id can only be specified for content: `projects`')
        assert content
        return os.path.join(DATA_PATH, content, project_id)
    
    def list_projects(self):
        '''Returns a list of all project_ids'''
        if os.path.isdir(self.path_to('projects')):
            return os.listdir(self.path_to('projects'))
        return []
    
    def list_referentials(self):
        '''Returns a list of all internal referentials'''
        if os.path.isdir(self.path_to('referentials')):
            return os.listdir(self.path_to('referentials'))
        return []    
    
    def remove_project(self, project_id):
        assert project_id and (project_id is not None)
        dir_path = self.path_to('projects', project_id) 
        if not os.path.isdir(dir_path):
            raise Exception('No project found with the following ID: {0}'.format(project_id))
        shutil.rmtree(dir_path)
    
        
if __name__ == '__main__':
    admin = Admin()
    
    _id = '8b3fbab040534afae137e2ae124ce152'
    
    for _id in admin.list_projects():
        #admin.remove_project(_id)
        proj = UserProject(_id)
        print(proj.project_id, proj.time_since_last_action())
        print(proj.list_csvs())
            
    
