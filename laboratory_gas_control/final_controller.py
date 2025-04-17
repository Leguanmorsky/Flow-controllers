import tkinter as tk
from tkinter import messagebox, scrolledtext
import propar
import nodes as nd
from itertools import count
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import csv
import time

class FlowControllerApp:
    def __init__(self, master):
        self.master = master
        self.master.title("Flow Controller")
        self.master.geometry("1700x850")
        self.nodes=None
        self.list_of_nodenames=[]
        self.list_of_nodes=[]
        self.auto_update_running = False  # Flag to track auto-updating
        
        self.node_names=[]
        self.subplots_names=["Setpoint","Measure","Valve output"]
        self.subplot_to_attr = {
            "Setpoint": "fsetpoint",
            "Measure": "fmeasure",
            "Valve output": "valve_output"
            # Add more if needed
        }
        # self.plots_in_node=len(self.subplots_names)
        # self.total_lines=len(self.node_names)*self.plots_in_node
        self.window_width = 100
        self.interval=250
        self.ymax=32000
        self.center_offset=self.window_width//2
        self.start_time = time.time()
        # self.x_vals=[]
        # self.y_vals = [[[] for _ in self.subplots_names] for _ in self.node_names]
        # self.colors_names=[["#6495ED","#0000FF","#00008B"],
        #                    ["#7FFFD4","#00FF00","#008000"],
        #                    ["#F4A460","#FFFF00","#8B0000"],
        #                    ["#EE82EE","#FF00FF","#8B008B"]]
        # self.labels=[[f"Node {n+1}-{self.subplots_names[v]}" for n in range(len(self.subplots_names))] for v in range(len(self.node_names))]
        self.fig, self.ax = plt.subplots(figsize=(10, 5))
        self.ax.set_ylim(-500, self.ymax)  # Lock y-axis
        
        self.ani = None  # Reserve animation object
        self.canvas = None  # Reserve canvas object
        
        self.create_widgets()
    
    def auto_update(self):
        """Automatically updates node parameters every 2 seconds if enabled."""
        if self.auto_update_running:
            for node_frame, node in zip(self.node_frames, self.list_of_nodes):
                # Get UI elements
                temp_label = node_frame.winfo_children()[1]  
                valve_output_label = node_frame.winfo_children()[3]  
                massF_label = node_frame.winfo_children()[5]  
                # valve_open_label = node_frame.winfo_children()[7]

                # Update displayed values
                node.update_temperature(temp_label)
                node.update_valve_output(valve_output_label)
                node.measure(massF_label)
                # node.append_to_csv()
                # node.update_open_valve(valve_open_label)

            # Schedule next update in 2 seconds
            self.master.after(750, self.auto_update)

    def toggle_auto_update(self):
        """Starts or stops auto-updating process."""
        if self.auto_update_running:
            self.auto_update_running = False
            self.update_button.config(text="Start Auto Update")
        else:
            self.auto_update_running = True
            self.update_button.config(text="Stop Auto Update")
            self.auto_update()  # Start the update loop

    def create_widgets(self):
        self.connect_button = tk.Button(self.master, text="Connect", command=self.connect_device)
        self.connect_button.grid(row=0, column=0, padx=10, pady=10)

        self.disconnect_button = tk.Button(self.master, text="Disconnect", command=self.disconnect_device, state=tk.DISABLED)
        self.disconnect_button.grid(row=0, column=1, padx=10, pady=10)
        # Placeholder for Node UI elements
        self.node_frames = []

    def update_ui_after_connection(self):
    # Clear existing UI elements for nodes
        for frame in self.node_frames:
            frame.destroy()
        self.node_frames = []
        
        self.plots_in_node=len(self.subplots_names)
        self.total_lines=len(self.node_names)*self.plots_in_node
        self.x_vals=[]
        self.y_vals = [[[] for _ in range(len(self.subplots_names))] for _ in range(len(self.node_names))]
        self.colors_names=[["#6495ED","#0000FF","#00008B"],
                           ["#7FFFD4","#00FF00","#008000"],
                           ["#F4A460","#FFFF00","#8B0000"],
                           ["#EE82EE","#FF00FF","#8B008B"]]
        self.labels=[[f"{self.node_names[v]}-{self.subplots_names[n]}" for n in range(len(self.subplots_names))] for v in range(len(self.node_names))]
        
        
        self.update_button = tk.Button(self.master, text="Start Auto Update", command=self.toggle_auto_update)
        self.update_button.grid(row=0, column=3, columnspan=2, pady=10)
        
         # Create a frame specifically for the matplotlib plot
        self.plot_frame = tk.Frame(self.master, bd=2, relief=tk.RIDGE)
        self.plot_frame.grid(row=1,rowspan=2, column=0, columnspan=2, padx=5, pady=5, sticky="nsew")
        self.setup_plot()
        
        # Dynamically create UI for each node in a horizontal layout
        for index, node in enumerate(self.list_of_nodes, start=1):
            # Create a frame for each node
            node_frame = tk.Frame(self.master, bd=2, relief=tk.SUNKEN, padx=5, pady=5)
            # Polynoms solve proper position of each node [[N_4,N_5],[N_6,N_33]] etc. Named for my specific nodes
            node_frame.grid(row=round((-1/3)*(index**3)+(5/2)*(index**2)-(31/6)*index+4), column=round((2/3)*(index**3)-5*(index**2)+(34/3)*index-5), padx=10, pady=10)
            # Optional naming of nodes (type of gas etc)
            # move_entry = tk.Entry(node_frame, width=10)
            # move_entry.grid(row=4, column=1, padx=2, pady=2)
            
            
            # Node Info (Name, ID)
            node_label = tk.Label(node_frame, text=f"{node.name} (ID: {node.node_id})", font=("Arial", 10, "bold"))
            node_label.grid(row=0, column=0, columnspan=2, sticky="w", padx=5, pady=5)

            # Temperature Display and Button
            temp_label = tk.Label(node_frame, text=f"Temp: {node.temperature} °C", font=("Arial", 10))
            temp_label.grid(row=1, column=0, sticky="w", padx=5, pady=5)

            temp_button = tk.Button(node_frame, text="Get Temp", command=lambda n=node, l=temp_label: n.update_temperature(l))
            temp_button.grid(row=1, column=1, padx=5, pady=5)

            # Valve output Display and Button
            valve_output_label = tk.Label(node_frame, text=f"Valve output: {node.valve_output}", font=("Arial", 10))
            valve_output_label.grid(row=2, column=0, sticky="w", padx=5, pady=5)

            valve_output_button = tk.Button(node_frame, text="Get valve_output", command=lambda n=node, l=valve_output_label: n.update_valve_output(l))
            valve_output_button.grid(row=2, column=1, padx=5, pady=5)

            # measure Display and Button
            massF_label = tk.Label(node_frame, text=f"fmeasure: {node.fmeasure}", font=("Arial", 10))
            massF_label.grid(row=3, column=0, sticky="w", padx=5, pady=5)

            flow_button = tk.Button(node_frame, text="Get measurment", command=lambda n=node, l=massF_label: n.measure(l))
            flow_button.grid(row=3, column=1, padx=5, pady=5)

            # Setpoint Entry and Send Button
            move_label = tk.Label(node_frame, text="Set setpoint: 0-32000", font=("Arial", 10))
            move_label.grid(row=4, column=0, sticky="w", padx=5, pady=2)

            move_entry = tk.Entry(node_frame, width=10)
            move_entry.grid(row=4, column=1, padx=5, pady=2)
            # move_entry.insert(0, "0")  # Initial value
            scale = tk.Scale(node_frame, from_=0, to=32767, orient=tk.HORIZONTAL, label="Set Setpoint: 0-32000",length=200)
            scale.grid(row=8, column=0, columnspan=3, padx=3, pady=3)
            scale.bind("<ButtonRelease-1>",lambda event, n=node, s=scale: n.setpoint(s.get()))
            # Send Button to set setpoint
            print(move_entry.get())
            send_button = tk.Button(node_frame, text="Send setpoint", command=lambda n=node, e=move_entry: n.setpoint(e.get()))
            send_button.grid(row=5, column=0, columnspan=2, pady=5)
            
            
            # ................................................................................................................
            valve_entry = tk.Entry(node_frame, width=10)
            valve_entry.grid(row=7, column=1, padx=5, pady=2)
            valve_entry.insert(0, "0")  # Initial value
            
            valve_open_label = tk.Label(node_frame, text=f"Open Valve: {node.valve_open}", font=("Arial", 10))
            valve_open_label.grid(row=6, column=0, sticky="w", padx=5, pady=2)
            
            valve_open_button = tk.Button(node_frame, text="Get open valve", command=lambda n=node, l=valve_open_label: n.update_open_valve(l))
            valve_open_button.grid(row=6, column=1, padx=5, pady=5)
            
            send_button = tk.Button(node_frame, text="Send", command=lambda n=node, e=valve_entry: n.open_valve(e.get()))
            send_button.grid(row=7, column=0, columnspan=2, pady=5)
            # ...................................................................................................................................
            
            
            # Save reference to the frame
            self.node_frames.append(node_frame)

        # Enable Disconnect Button after connection
        self.disconnect_button.config(state=tk.NORMAL)

    def connect_device(self):
        try:
            device = propar.instrument("COM9")
            self.nodes=device.master.get_nodes()
            messagebox.showinfo("Connected", "Successfully connected to the device.")
            # Node 1: {'address': 4, 'type': 'DMFC', 'serial': 'M24207457D', 'id': '\x07SNM24207457D', 'channels': 1}
            if self.nodes:
                for n in range(0,len(self.nodes)):
                    node = nd.Node(self.nodes[n]["id"], f"Node_{self.nodes[n]['address']}",propar.instrument("COM9",self.nodes[n]['address']), None, None, None,0,None,None,None)
                    self.node_names.append(node.name)
                    self.list_of_nodes.append(node)
                    # self.list_of_nodes = [node4, node5, node6, node33]
                self.update_ui_after_connection()
            else:
                messagebox.showerror("Error", "No nodes detected.")
            
        except Exception as e:
            messagebox.showerror("Error", f"Failed to connect: {e}")
            # [{'address': 4, 'type': 'DMFC', 'serial': 'M24207457D', 'id': '\x07SNM24207457D', 'channels': 1}, 
            #  {'address': 5, 'type': 'DMFC', 'serial': 'M24207457B', 'id': '\x07SNM24207457B', 'channels': 1},
            #  {'address': 6, 'type': 'DMFC', 'serial': 'M24207457A', 'id': '\x07SNM24207457A', 'channels': 1}]

    def disconnect_device(self):
        if self.flow_device:
            self.flow_device = None
            messagebox.showinfo("Disconnected", "Successfully disconnected from the device.")
        else:
            messagebox.showwarning("Warning", "No device connected.")
                    
    def animation(self,i):
        current_time=time.time()-self.start_time
        self.x_vals.append(current_time)
        while self.x_vals and self.x_vals[0] < current_time - self.center_offset:
            self.x_vals.pop(0)
            for node_data in self.y_vals:
                for line_data in node_data:
                    if line_data:
                        line_data.pop(0)
        for node_index, node in enumerate(self.list_of_nodes):  # self.nodes are your node objects
            for line_index, subplot_name in enumerate(self.subplots_names):
                value = getattr(node, self.subplot_to_attr[subplot_name])  # You need to define this logic
                self.y_vals[node_index][line_index].append(value)
                # self.seek_csv(self.node_names[node],self.subplots_names[line])
        self.ax.clear()
        self.ax.set_ylim(-500, self.ymax)
        
        # Keep y-axis fixed
        if current_time <= self.center_offset:
            self.ax.set_xlim(0, self.window_width)
        else:
            self.ax.set_xlim(current_time - self.center_offset, current_time + self.center_offset)

        self.ax.set_xlabel("Time (s)")
        self.ax.set_ylabel("Value")
        # Show only the last 'window_size' points
        for node in range(len(self.node_names)):
            for line in range(len(self.subplots_names)):
                self.ax.plot(self.x_vals[-int((self.center_offset*(1000/self.interval))):],
                        self.y_vals[node][line][-int((self.center_offset*(1000/self.interval))):],
                        label=self.labels[node][line],
                        color=self.colors_names[node][line],
                        linewidth=1.5)

        self.ax.legend(loc='upper left', fontsize=8, ncol=len(self.node_names))
        self.ax.grid(True)
        
    def setup_plot(self):
        self.canvas = FigureCanvasTkAgg(self.fig, master=self.plot_frame)
        self.canvas.get_tk_widget().grid(row=0, column=0, sticky="nsew")
        self.ani = FuncAnimation(
            self.fig,
            self.animation,
            interval=self.interval,
            cache_frame_data=False,
            blit=False
    )
def main():
    root = tk.Tk()
    app = FlowControllerApp(master=root)
    root.mainloop()

if __name__ == "__main__":
    main()