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
import os
import numpy as np
import serial.tools.list_ports

DEFAULT_PORT = "COM9"

def close_port(port):
    """Closes the serial port opened by propar and forgets the cached master."""
    master = propar._PROPAR_MASTERS.pop(port, None)
    if master:
        try:
            master.stop()
        except Exception:
            pass

def find_port():
    """Returns (port, nodes) of the first COM port with Bronkhorst nodes.
    Order: FLOW_COM_PORT env var, COM9, then every other available port.
    Bluetooth serial ports are skipped - opening them can hang or crash Python."""
    ports = serial.tools.list_ports.comports()
    available = [p.device for p in ports]
    scanned = [p.device for p in ports if "BTHENUM" not in (p.hwid or "").upper() and "bluetooth" not in (p.description or "").lower()]
    forced = os.environ.get("FLOW_COM_PORT")
    candidates = [forced] + ([DEFAULT_PORT] if DEFAULT_PORT in scanned else []) + scanned
    tried = []
    for port in candidates:
        if not port or port in tried:
            continue
        tried.append(port)
        try:
            nodes = propar.instrument(port).master.get_nodes()
            if nodes:
                return port, nodes
        except Exception:
            pass
        close_port(port)
    raise Exception(f"No Bronkhorst device found (tried: {', '.join(tried) or 'none'}; "
                    f"available ports: {', '.join(available) or 'none'}). "
                    f"Check the USB cable/driver or start with: run.bat COMx")

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
                # increment_count_label = node_frame.winfo_children()[7]

                # Update displayed values
                node.update_temperature(temp_label)
                node.update_valve_output(valve_output_label)
                node.measure(massF_label)
                # node.append_to_csv()
                # node.update_open_valve(increment_count_label)

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
        self.update_button.grid(row=0, column=3, pady=10)
        
        open_table_button = tk.Button(self.master, text="Rename Nodes", command=self.show_node_rename_table)
        open_table_button.grid(row=0, column=4, pady=10)
        
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
            node_label = tk.Label(node_frame, text=f"{node.name} ({node.node_id})", font=("Arial", 10, "bold"),fg=self.colors_names[index-1][1])
            node_label.grid(row=0, column=0, columnspan=2, sticky="w", padx=5, pady=5)
            
            # Button to run a table for sequences of setpoints
            open_table_button = tk.Button(node_frame, text="Program", command=self.sequence_of_setpoints_table)
            open_table_button.grid(row=0, column=2, pady=10)

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

            setpoint_var = tk.StringVar(value='0') # Default to '0'
            node.gui_setpoint_var = setpoint_var
            move_entry = tk.Entry(node_frame, width=10, textvariable=setpoint_var)
            move_entry.grid(row=4, column=1, padx=5, pady=2)
            move_entry.bind("<Return>", lambda e, v=setpoint_var, n=node: update_setpoint_from_var(e, v, n)) # <-- Bind to <Return> key
            # move_entry.insert(0, "0")  # Initial value
            scale_frame = tk.Frame(node_frame)
            # Place this new frame on the left, spanning 3 columns of the parent node_frame
            scale_frame.grid(row=9, column=0, columnspan=3, padx=0, pady=3, sticky='w')

            # 2. Place the scale and buttons INSIDE the new scale_frame
            
            scale_frame = tk.Frame(node_frame)
            # Place this new frame on the left, spanning 3 columns of the parent node_frame
            scale_frame.grid(row=9, column=0, columnspan=3, padx=0, pady=3, sticky='w')

            # 2. Place the scale and buttons INSIDE the new scale_frame
            
            # Scale length set to 200, master is now scale_frame
            scale = tk.Scale(scale_frame, from_=0, to=32767, orient=tk.HORIZONTAL, 
                            label="Setpoint Control:", length=200, 
                            variable=setpoint_var, showvalue=0) # <-- Use shared var, hide default value
            
            # Place scale in column 1 of scale_frame
            scale.grid(row=0, column=1, padx=0, pady=0) # No internal padding
            scale.bind("<ButtonRelease-1>", lambda e, v=setpoint_var, n=node: update_setpoint_from_var(e, v, n)) # <-- Bind to mouse release
            left_button = tk.Button(scale_frame, text="<", 
                                    command=lambda v=setpoint_var, n=node: increment_scale(v, n, -10))
            left_button.grid(row=0, column=0, padx=(5,0), pady=0, sticky='ns') 
            right_button = tk.Button(scale_frame, text=">", 
                                    command=lambda v=setpoint_var, n=node: increment_scale(v, n, 10))
            right_button.grid(row=0, column=2, padx=(0,5), pady=0, sticky='ns')

            # Send Button to set setpoint
            send_button = tk.Button(node_frame, text="Send setpoint", command=lambda n=node, e=move_entry: n.setpoint(e.get()))
            send_button.grid(row=5, column=0, columnspan=2, pady=5)
            
            # --- Helper Function (place this with your other functions) ---
            def adjust_setpoint(node, scale, amount):
                """
                Adjusts the scale's value by a given amount, ensures it stays
                within bounds, updates the scale widget, and calls the node's
                setpoint method.
                """
                # Get the scale's limits
                lower_limit = scale.cget("from")
                upper_limit = scale.cget("to")
                
                # Calculate the new value
                new_val = scale.get() + amount
                
                # Clamp the value to stay within the scale's range
                new_val = max(lower_limit, min(new_val, upper_limit))
                
                # Update the scale's visual position
                scale.set(new_val)
                
                # Call your original function with the new value
                node.setpoint(new_val)
            # ................................................................................................................
            set_var = tk.StringVar(value="0")
            speed_var = tk.StringVar(value="0")
            
            increment_count_set_label = tk.Label(node_frame, text=f"Set to: (0-32000)", font=("Arial", 10))
            increment_count_set_label.grid(row=6, column=0, sticky="w", padx=5, pady=2)
            
            increment_count_speed_label = tk.Label(node_frame, text=f"Speed P/s", font=("Arial", 10))
            increment_count_speed_label.grid(row=6, column=1, sticky="w", padx=5, pady=2)
            
            increment_count_set_entry = tk.Entry(node_frame, width=10, textvariable=set_var)
            increment_count_set_entry.grid(row=7, column=0, padx=5, pady=2)
            
            increment_count_speed_entry = tk.Entry(node_frame, width=10,textvariable=speed_var)
            increment_count_speed_entry.grid(row=7, column=1, padx=5, pady=2)
            
            increment_count_run_button = tk.Button(node_frame, text="RUN", command=lambda n=node, e1=increment_count_set_entry, e2=increment_count_speed_entry: n.run_increment_count(e1.get(), e2.get()))
            increment_count_run_button.grid(row=7, column=2, padx=5, pady=5)
            
            increment_count_time_label = tk.Label(node_frame, text=f"It will take approx:", font=("Arial", 10))
            increment_count_time_label.grid(row=8, column=0, columnspan=2, sticky="w", padx=5, pady=2)
            
            increment_count_stop_button = tk.Button(node_frame, text="STOP", command=lambda n=node, e1=increment_count_set_entry, e2=increment_count_speed_entry: n.stop_increment_count())
            increment_count_stop_button.grid(row=8, column=2, padx=5, pady=5)
            
            def update_estimated_time(label, var1, var2, node_obj):
                try:
                    set_val = int(var1.get())
                    speed_val = float(var2.get())

                    # --- FIX ---
                    # Get the current value from the node object
                    try:
                        # We must convert fsetpoint, as it's likely a string
                        current_val = float(node_obj.fsetpoint)
                    except (ValueError, TypeError, AttributeError):
                        # Handle cases where fsetpoint is None or not set yet
                        label.config(text="It will take approx: ?")
                        return

                    # Calculate the absolute difference
                    difference = abs(set_val - current_val)
                    # --- END FIX ---
                    
                    if speed_val > 0:
                        # Your logic for incrementing is float(speed) * 2 every 2 seconds,
                        # which simplifies to an effective speed of float(speed) units/sec.
                        # So, this calculation is correct.
                        est_time = difference / speed_val 
                        label.config(text=f"It will take approx: {format_time(est_time)}")
                    else:
                        label.config(text="It will take approx: ∞")
                
                except ValueError:
                    # This catches errors from var1.get() or var2.get()
                    label.config(text="It will take approx: ?")
                    
            def format_time(seconds):
                seconds = int(seconds)
                days, seconds = divmod(seconds, 86400)
                hours, seconds = divmod(seconds, 3600)
                minutes, seconds = divmod(seconds, 60)
                
                parts = []
                if days > 0:
                    parts.append(f"{days} d")
                if hours > 0:
                    parts.append(f"{hours} h")
                if minutes > 0:
                    parts.append(f"{minutes} min")
                parts.append(f"{seconds} s")
                
                return ' '.join(parts)
            def increment_scale(var, node_obj, amount):
                try:
                    # Get value from the shared variable
                    current_val = float(var.get())
                except ValueError:
                    current_val = 0
                
                new_val = current_val + amount
                
                # Clamp the value within the scale's bounds (0 to 32767)
                if new_val > 32767:
                    new_val = 32767
                elif new_val < 0:
                    new_val = 0
                var.set(str(new_val))
                node_obj.setpoint(new_val)
            
            def update_setpoint_from_var(event, var, node_obj):
                try:
                    new_val = float(var.get())
                    
                    # Clamp value just in case
                    if new_val > 32767: 
                        new_val = 32767
                    elif new_val < 0: 
                        new_val = 0
                    
                    # Update variable again in case it was clamped
                    var.set(str(new_val)) 
                    
                    # Send the clamped value to the correct node
                    node_obj.setpoint(new_val)
                except ValueError:
                    # On invalid input (e.g., "abc"), reset to 0
                    var.set('0')
                    node_obj.setpoint(0)
            # Attach the trace
            set_var.trace_add("write", lambda *_, lbl=increment_count_time_label, v1=set_var, v2=speed_var, n=node: update_estimated_time(lbl, v1, v2, n))
            speed_var.trace_add("write", lambda *_, lbl=increment_count_time_label, v1=set_var, v2=speed_var, n=node: update_estimated_time(lbl, v1, v2, n))
            # ...................................................................................................................................
            
            # Save reference to the frame
            self.node_frames.append(node_frame)
        # Enable Disconnect Button after connection
        self.disconnect_button.config(state=tk.NORMAL)
        
    def connect_device(self):
        try:
            self.port, self.nodes = find_port()
            messagebox.showinfo("Connected", f"Successfully connected to the device ({self.port}).")
            # Node 1: {'address': 4, 'type': 'DMFC', 'serial': 'M24207457D', 'id': '\x07SNM24207457D', 'channels': 1}
            self.node_names.clear()
            self.list_of_nodes.clear()
            if self.nodes:
                for n in range(0,len(self.nodes)):
                    node = nd.Node(self.nodes[n]["id"], f"Node_{self.nodes[n]['address']}",propar.instrument(self.port,self.nodes[n]['address']), None, None, None,0,None,self.master)
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
        self.auto_update_running = False  # Stop auto-update if it's running

        # Stop animation
        if self.ani:
            self.ani.event_source.stop()

        # Clear matplotlib plot
        if self.ax:
            self.ax.clear()
            self.canvas.draw()

        # Clear any node-related frames
        for frame in self.node_frames:
            frame.destroy()
        self.node_frames.clear()

        # Release the COM port so Connect works again
        if getattr(self, "port", None):
            close_port(self.port)
            self.port = None

        # Reset internal state
        self.nodes = None
        self.list_of_nodes.clear()
        self.node_names.clear()
        self.y_vals.clear()
        self.x_vals.clear()
        self.start_time = time.time()

        # Destroy plot frame if it exists
        if hasattr(self, 'plot_frame') and self.plot_frame:
            self.plot_frame.destroy()
            self.plot_frame = None

        # Disable Disconnect button
        self.disconnect_button.config(state=tk.DISABLED)

        # Destroy all widgets and recreate the initial state
        for widget in self.master.winfo_children():
            widget.destroy()

        self.create_widgets()
        messagebox.showinfo("Disconnected", "Successfully disconnected and reset.")
        
    def show_node_rename_table(self):
        table_window = tk.Toplevel(self.master)
        table_window.title("Rename Nodes")

        header1 = tk.Label(table_window, text="Current Name", font=("Arial", 10, "bold"))
        header1.grid(row=0, column=0, padx=5, pady=5)

        header2 = tk.Label(table_window, text="New Name", font=("Arial", 10, "bold"))
        header2.grid(row=0, column=1, padx=5, pady=5)

        entry_fields = []
        for idx, node in enumerate(self.node_names):
            current_name_label=tk.Label(table_window, text=node)
            current_name_label.grid(row=idx+1, column=0, padx=10, pady=5, sticky="w")

            new_name_entry = tk.Entry(table_window, width=20)
            new_name_entry.grid(row=idx+1, column=1, padx=10, pady=5)
            
            entry_fields.append(new_name_entry)
        save_button=tk.Button(table_window, text="Save",command=lambda list=entry_fields: self.save_new_names(list))
        save_button.grid(row=len(self.node_names)+1, column=1, padx=5, pady=5)
    def save_new_names(self,list_of_entries):
        for i in range(len(self.node_names)):
            self.list_of_nodes[i].node_id=list_of_entries[i].get()
    def sequence_of_setpoints_table(self):
        program_table=tk.Toplevel(self.master)
        program_table.title("Seq control table")
        
        header_choose = tk.Label(program_table, text="Program type", font=("Arial", 10, "bold")).grid(row=0, column=0, padx=5, pady=5)
        header_left = tk.Label(program_table, text="Setpoint (0-32k)", font=("Arial", 10, "bold")).grid(row=0, column=1, padx=5, pady=5)
        header_mid = tk.Label(program_table, text="Speed P/s", font=("Arial", 10, "bold")).grid(row=0, column=2, padx=5, pady=5)
        header_right = tk.Label(program_table, text="Duration s", font=("Arial", 10, "bold")).grid(row=0, column=3, padx=5, pady=5)
        
        program_types_config = {
            "Ramp (Rate)":    {"Setpoint": True, "Rate": True,  "Duration": False},
            "Ramp (Time)":    {"Setpoint": True, "Rate": False, "Duration": True},
            "Dwell":          {"Setpoint": True, "Rate": False, "Duration": True},
            "Step":           {"Setpoint": True, "Rate": False, "Duration": False},
            # Add more types if needed, e.g., an empty row type
            "--- Select ---": {"Setpoint": False, "Rate": False, "Duration": False} # Initial placeholder
        }
        self.program_types=list(program_types_config.keys())
        self.program_rows_data = []

        num_rows_to_create = 8
        for i in range(num_rows_to_create):
            row_index = i + 1
            row_widgets = {}

            type_var = tk.StringVar(program_table)
            type_var.set(self.program_types[0]) # Set initial value

            # --- Using command with a lambda ---
            # The lambda receives the selected_value from OptionMenu's command
            # and then explicitly passes it along with the row_widgets to update_row_state.
            type_dropdown = tk.OptionMenu(program_table, type_var, *self.program_types,
                                          command=lambda selected_val, widgets=row_widgets:
                                              self.update_row_state(selected_val, widgets, program_types_config))
            type_dropdown.grid(row=row_index, column=0, padx=5, pady=2, sticky="ew")
            row_widgets["type_var"] = type_var # Still useful for getting current value if needed later
            row_widgets["type_dropdown"] = type_dropdown # Store for reference

            # ... (entry fields, same as before) ...
            setpoint_entry = tk.Entry(program_table, width=15)
            setpoint_entry.grid(row=row_index, column=1, padx=5, pady=2)
            row_widgets["setpoint_entry"] = setpoint_entry

            rate_entry = tk.Entry(program_table, width=15)
            rate_entry.grid(row=row_index, column=2, padx=5, pady=2)
            row_widgets["rate_entry"] = rate_entry

            duration_entry = tk.Entry(program_table, width=15)
            duration_entry.grid(row=row_index, column=3, padx=5, pady=2)
            row_widgets["duration_entry"] = duration_entry
            
            self.program_rows_data.append(row_widgets)

            # Initialize the state of the row based on the initial selection
            self.update_row_state(type_var.get(), row_widgets, program_types_config)

        # --- Program Parameters Section (below the main table) ---
        # Adjust row index for placement
        params_start_row = num_rows_to_create + 1
        tk.Label(program_table, text="Program Parameters", font=("Arial", 10, "bold")).grid(row=params_start_row, column=0, columnspan=2, padx=5, pady=10, sticky="w")

        self.continuous_cycling_var = tk.BooleanVar(program_table)
        continuous_cycling_check = tk.Checkbutton(program_table, text="Continuous Cycling", variable=self.continuous_cycling_var)
        continuous_cycling_check.grid(row=params_start_row + 1, column=0, columnspan=2, padx=5, pady=2, sticky="w")

        self.holdback_var = tk.BooleanVar(program_table)
        holdback_check = tk.Checkbutton(program_table, text="Holdback", variable=self.holdback_var)
        holdback_check.grid(row=params_start_row + 2, column=0, columnspan=2, padx=5, pady=2, sticky="w")

        tk.Label(program_table, text="Program Cycles:").grid(row=params_start_row + 1, column=2, padx=5, pady=2, sticky="w")
        self.program_cycles_entry = tk.Entry(program_table, width=10)
        self.program_cycles_entry.grid(row=params_start_row + 1, column=3, padx=5, pady=2, sticky="w")
        self.program_cycles_entry.insert(0, "1") # Default value from image

        tk.Label(program_table, text="Holdback Band °C:").grid(row=params_start_row + 2, column=2, padx=5, pady=2, sticky="w")
        self.holdback_band_entry = tk.Entry(program_table, width=10)
        self.holdback_band_entry.grid(row=params_start_row + 2, column=3, padx=5, pady=2, sticky="w")
        self.holdback_band_entry.insert(0, "1.0") # Default value from image

        tk.Label(program_table, text="Time Units:").grid(row=params_start_row + 3, column=2, padx=5, pady=2, sticky="w")
        self.time_units_var = tk.StringVar(program_table)
        self.time_units_var.set("s") # Default
        time_units_options = ["s", "min", "hr"] # From image, 's' is default
        time_units_dropdown = tk.OptionMenu(program_table, self.time_units_var, *time_units_options)
        time_units_dropdown.grid(row=params_start_row + 3, column=3, padx=5, pady=2, sticky="w")


        # --- Control Buttons (Run, Stop, Hold, Load, Save) ---
        button_row = params_start_row + 4
        tk.Button(program_table, text="Run").grid(row=button_row, column=0, padx=5, pady=10)
        tk.Button(program_table, text="Stop").grid(row=button_row, column=1, padx=5, pady=10)
        tk.Button(program_table, text="Hold").grid(row=button_row, column=2, padx=5, pady=10)
        tk.Button(program_table, text="Load...").grid(row=button_row + 1, column=1, padx=5, pady=5)
        tk.Button(program_table, text="Save...").grid(row=button_row + 1, column=2, padx=5, pady=5)


    def update_row_state(self, selected_type, row_widgets, config):
        """
        Updates the state (enabled/disabled) of entry widgets in a row
        based on the selected program type.
        """
        if selected_type not in config:
            print(f"Warning: Configuration for type '{selected_type}' not found.")
            return

        type_config = config[selected_type]

        # Update Setpoint entry
        state_setpoint = 'normal' if type_config["Setpoint"] else 'disabled'
        row_widgets["setpoint_entry"].config(state=state_setpoint)

        # Update Rate entry
        state_rate = 'normal' if type_config["Rate"] else 'disabled'
        row_widgets["rate_entry"].config(state=state_rate)

        # Update Duration entry
        state_duration = 'normal' if type_config["Duration"] else 'disabled'
        row_widgets["duration_entry"].config(state=state_duration)


    def get_program_data(self):
        """
        A placeholder function to show how you'd retrieve all the data
        from the created table.
        """
        print("--- Retrieving Program Data ---")
        program_segments = []
        for row in self.program_rows_data:
            segment_type = row["type_var"].get()
            setpoint = row["setpoint_entry"].get()
            rate = row["rate_entry"].get()
            duration = row["duration_entry"].get()

            # You'd add validation here (e.g., convert to float, check ranges)
            program_segments.append({
                "type": segment_type,
                "setpoint": setpoint,
                "rate": rate,
                "duration": duration
            })
            print(f"Segment: Type={segment_type}, Setpoint={setpoint}, Rate={rate}, Duration={duration}")

        print("\n--- Program Parameters ---")
        print(f"Continuous Cycling: {self.continuous_cycling_var.get()}")
        print(f"Holdback: {self.holdback_var.get()}")
        print(f"Program Cycles: {self.program_cycles_entry.get()}")
        print(f"Holdback Band °C: {self.holdback_band_entry.get()}")
        print(f"Time Units: {self.time_units_var.get()}")

        
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
                if value is None:
                    self.y_vals[node_index][line_index].append(np.nan)
                else:
                    # You should also convert to float here to be safe
                    try:
                        self.y_vals[node_index][line_index].append(float(value))
                    except (ValueError, TypeError):
                        # If conversion fails, append nan
                        self.y_vals[node_index][line_index].append(np.nan)
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