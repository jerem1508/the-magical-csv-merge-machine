#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Fri Aug 18 16:42:41 2017

@author: m75380

# Ideas: Learn analysers and weights for blocking on ES directly
# Put all fields to learn blocking by exact match on other fields

https://www.elastic.co/guide/en/elasticsearch/reference/current/multi-fields.html

$ ./bin/elasticsearch
"""

import pandas as pd

from es_labeller import Labeller


dir_path = 'data/sirene'
chunksize = 3000
file_len = 10*10**6


sirene_index_name = '123vivalalgerie2'

test_num = 5
if test_num == 0:
    source_file_path = 'local_test_data/source.csv'
    match_cols = [{'source': 'commune', 'ref': 'LIBCOM'},
                  {'source': 'lycees_sources', 'ref': 'NOMEN_LONG'}]    
    source_sep = ','
    source_encoding = 'utf-8'
    
    ref_table_name = sirene_index_name
    
elif test_num == 1:
    source_file_path = 'local_test_data/integration_5/data_ugly.csv'
    match_cols = [{'source': 'VILLE', 'ref': 'L6_NORMALISEE'},
                  {'source': 'ETABLISSEMENT', 'ref': 'NOMEN_LONG'}]
    source_sep = ';'
    source_encoding = 'windows-1252'
    
    ref_table_name = sirene_index_name
    
elif test_num == 2:
    # ALIM to SIRENE
    source_file_path = 'local_test_data/integration_3/export_alimconfiance.csv'
    match_cols = [{'source': 'Libelle_commune', 'ref': 'LIBCOM'},
                  #{'source': 'Libelle_commune', 'ref': 'L6_NORMALISEE'},
                  {'source': 'ods_adresse', 'ref': 'L4_NORMALISEE'},
                  {'source': 'APP_Libelle_etablissement', 'ref': ('L1_NORMALISEE', 
                                                        'ENSEIGNE', 'NOMEN_LONG')}]

    source_sep = ';'
    source_encoding = 'utf-8'
    
    ref_table_name = sirene_index_name
    
elif test_num == 3:
    # HAL to GRID
    source_file_path = 'local_test_data/integration_4/hal.csv'

    match_cols = [{
                    "source": ("parentName_s", "label_s"),
                    "ref": ("Name", "City")
                  }]
    source_sep = '\t'
    source_encoding = 'utf-8'
    
    ref_table_name = '01c670508e478300b9ab7c639a76c871'

elif test_num == 4:
    source_file_path = 'local_test_data/integration_6_hal_2/2017_09_15_HAL_09_08_2015_Avec_RecageEchantillon.csv'

    match_cols = [{
                    "source": ("parentName_s", "label_s"),
                    "ref": ("Name", "City")
                  }]
    source_sep = ';'
    source_encoding = 'ISO-8859-1'
    
    ref_table_name = '01c670508e478300b9ab7c639a76c871'

elif test_num == 5:
    # Test on very short file
    source_file_path = 'local_test_data/source_5_lines.csv'
    match_cols = [{'source': 'commune', 'ref': 'LIBCOM'},
                  {'source': 'lycees_sources', 'ref': 'NOMEN_LONG'}]    
    source_sep = ','
    source_encoding = 'utf-8'
    
    ref_table_name = sirene_index_name    

else:
    raise Exception('Not a valid test number')


source = pd.read_csv(source_file_path, 
                    sep=source_sep, encoding=source_encoding,
                    dtype=str, nrows=chunksize)
source = source.where(source.notnull(), '')


if test_num in [0,1,2,5]:
    columns_to_index = {
        'SIRET': {},
        'SIREN': {},
        'NIC': {},
        'L1_NORMALISEE': {
            'french', 'integers', 'n_grams', 'city'
        },
        'L4_NORMALISEE': {
            'french', 'integers', 'n_grams', 'city'
        },
        'L6_NORMALISEE': {
            'french', 'integers', 'n_grams', 'city'
        },
        'L1_DECLAREE': {
            'french', 'integers', 'n_grams', 'city'
        },
        'L4_DECLAREE': {
            'french', 'integers', 'n_grams', 'city'
        },
        'L6_DECLAREE': {
            'french', 'integers', 'n_grams', 'city'
        },
        'LIBCOM': {
            'french', 'n_grams', 'city'
        },
        'CEDEX': {},
        'ENSEIGNE': {
            'french', 'integers', 'n_grams', 'city'
        },
        'NOMEN_LONG': {
            'french', 'integers', 'n_grams', 'city'
        },
        #Keyword only 'LIBNATETAB': {},
        'LIBAPET': {},
        'PRODEN': {},
        'PRODET': {}
    }
        
elif test_num in [3, 4]:
    columns_to_index = {
            "Name": {
                    'french', 'whitespace', 'integers', 'end_n_grams', 'n_grams', 'city'
                    },
            "City": {
                    'french', 'whitespace', 'integers', 'end_n_grams', 'n_grams', 'city'
                    }
            }

if test_num == 2:
    columns_certain_match = {'source': ['SIRET'], 'ref': ['SIRET']}
    labeller = Labeller(source, ref_table_name, match_cols, columns_to_index)
    labeller.auto_label(columns_certain_match)
    
elif test_num == 4:
    columns_certain_match = {'source': ['grid'], 'ref': ['ID']}
    labeller = Labeller(source, ref_table_name, match_cols, columns_to_index)
    
else:    
    labeller = Labeller(source, ref_table_name, match_cols, columns_to_index)


for i in range(100):  
    if not labeller.has_labels:
        break
    
    for x in range(10):
        if labeller.has_labels:
            user_input = labeller.console_input()
            if labeller.answer_is_valid(user_input):
                labeller.update(user_input)
                break
            else:
                print('Invalid answer ("y"/"1", "n"/"0", "u" or "p")')
        else:
            break
    
    
    
    
    if i == 15:
        print('Updating musts')
        if test_num == 0:
            labeller.update_musts({'NOMEN_LONG': ['lycee']},
                                  {'NOMEN_LONG': ['ass', 'association', 'sportive', 
                                                  'foyer', 'maison', 'amicale']})

print(labeller.to_emit())
