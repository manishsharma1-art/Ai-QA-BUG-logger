import csv

file_path = 'c:/Users/Imart/Documents/QA_BUG_Logger/assets/assetstraining_data_6000.csv.csv'

try:
    with open(file_path, 'r', encoding='utf-8') as f:
        reader = csv.reader(f)
        header = next(reader)
        print(f"Header ({len(header)} columns): {header}")
        
        row_count = 0
        error_rows = []
        for i, row in enumerate(reader, start=2):
            row_count += 1
            if len(row) != len(header):
                error_rows.append((i, len(row)))
                
        print(f"Total data rows parsed: {row_count}")
        if error_rows:
            print(f"Found {len(error_rows)} rows with incorrect number of columns.")
            print(f"First 10 error rows: {error_rows[:10]}")
        else:
            print("All rows have the correct number of columns.")
            
except Exception as e:
    print(f"Error reading file: {e}")
