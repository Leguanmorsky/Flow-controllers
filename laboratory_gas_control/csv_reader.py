import csv
import time
import random
with open("data.csv","w") as w:
    random_writer=csv.writer(w)
    while True:
        value=random.randint(0,100)
        



# with open("data.csv", "r") as f:
#     header_line = f.readline().strip()
#     fieldnames = header_line.split(',')
#     f.seek(0, 2)

#     while True:
#         line = f.readline()
#         if line.strip():
#             row = next(csv.DictReader([line], fieldnames=fieldnames))
#             print(f"New row: time={row['time']}  value={row['value']}")
#         else:
#             time.sleep(0.5)