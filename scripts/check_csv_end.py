import csv

file_path = 'c:/Users/Imart/Documents/QA_BUG_Logger/assets/assetstraining_data_6000.csv.csv'

try:
    with open(file_path, 'r', encoding='utf-8') as f:
        reader = list(csv.reader(f))
        print(f"Total lines read from CSV: {len(reader)}")
        print(f"Last row ID: {reader[-1][0]} Subject: {reader[-1][2]}")
        
except Exception as e:
    print(f"Error reading file: {e}")
