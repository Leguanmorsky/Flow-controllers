import random
import time
import csv
from itertools import count
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation
plt.style.use("fivethirtyeight")

def seek_csv(node,column):
    with open(f"csvData_{node}.csv", "r") as f:
        reader = csv.DictReader(f)
        f.seek(0, 2)

        while True:
            line = f.readline()
            if line:
                row = next(csv.DictReader([line], fieldnames=reader.fieldnames))
                print(f"New row: value={row[column]}")
                return int(row[column])
            else:
                time.sleep(0.1)

node_names=["Node_4","Node_5","Node_6"]
plots_in_node=3
total_lines=len(node_names)*plots_in_node

window_width = 100
interval=250
ymax=32000
center_offset=window_width//2

start_time = time.time()
x_vals=[]

# Colors and labels
subplots_names=["Setpoint","Measure","Valve output"]
y_vals = [[[] for _ in range(len(subplots_names))] for _ in range(len(node_names))]
colors_names=[["#6495ED","#0000FF","#00008B"],["#7FFFD4","#00FF00","#008000"],["#F4A460","#FFFF00","#8B0000"],["#EE82EE","#FF00FF","#8B008B"]]
labels=[[f"Node {n+1}-{subplots_names[v]}" for n in range(len(node_names))] for v in range(plots_in_node)]

fig, ax = plt.subplots(figsize=(14, 6))
ax.set_ylim(-10, ymax)  # Lock y-axis

def animation(i):
    current_time=time.time()-start_time
    x_vals.append(current_time)
    for node in range(len(node_names)):
        for line in range(len(node_names)):
            y_vals[node][line].append(seek_csv(node_names[node],subplots_names[line]))
    ax.clear()
    ax.set_ylim(-10, ymax)
    
    # Keep y-axis fixed
    if current_time <= center_offset:
        ax.set_xlim(0, window_width)
    else:
        ax.set_xlim(current_time - center_offset, current_time + center_offset)

    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Value")
    # Show only the last 'window_size' points
    for node in range(len(node_names)):
        for line in range(len(subplots_names)):
            ax.plot(x_vals[-int((center_offset*(1000/interval))):],
                    y_vals[-int((center_offset*(1000/interval))):],
                    label=labels[node][line],
                    color=colors_names[node][line],
                    linewidth=1.5)

    # Optional: Label axes
    
ani=FuncAnimation(plt.gcf(),animation,interval=interval, cache_frame_data=False)


plt.tight_layout()
plt.show()