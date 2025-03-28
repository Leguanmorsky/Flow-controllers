import tkinter as tk
from tkinter import messagebox, scrolledtext
import propar
import nodes as nd

class FlowControllerApp:
    def __init__(self, master):
        self.master = master
        self.master.title("Flow Controller")
        self.master.geometry("1200x600")
        self.nodes=None
        self.list_of_nodes=[]
        self.create_widgets()

    def create_widgets(self):
        # Connect/Disconnect Buttons
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

        # Dynamically create UI for each node in a horizontal layout
        for index, node in enumerate(self.list_of_nodes, start=1):
            # Create a frame for each node
            node_frame = tk.Frame(self.master, bd=2, relief=tk.SUNKEN, padx=5, pady=5)
            node_frame.grid(row=1, column=index, padx=10, pady=10)

            # Node Info (Name, ID)
            node_label = tk.Label(node_frame, text=f"{node.name} (ID: {node.node_id})", font=("Arial", 10, "bold"))
            node_label.grid(row=0, column=0, columnspan=2, sticky="w", padx=5, pady=5)

            # Temperature Display and Button
            temp_label = tk.Label(node_frame, text=f"Temp: {node.temperature} °C", font=("Arial", 10))
            temp_label.grid(row=1, column=0, sticky="w", padx=5, pady=5)

            temp_button = tk.Button(node_frame, text="Get Temp", command=lambda n=node, l=temp_label: n.update_temperature(l))
            temp_button.grid(row=1, column=1, padx=5, pady=5)

            # Pressure Display and Button
            pressure_label = tk.Label(node_frame, text=f"Pressure: {node.pressure} bar", font=("Arial", 10))
            pressure_label.grid(row=2, column=0, sticky="w", padx=5, pady=5)

            pressure_button = tk.Button(node_frame, text="Get Pressure", command=lambda n=node, l=pressure_label: n.update_pressure(l))
            pressure_button.grid(row=2, column=1, padx=5, pady=5)

            # Valve Output Display and Button
            massF_label = tk.Label(node_frame, text=f"VolumeF: {node.valve_output}", font=("Arial", 10))
            massF_label.grid(row=3, column=0, sticky="w", padx=5, pady=5)

            flow_button = tk.Button(node_frame, text="Get Flow", command=lambda n=node, l=massF_label: n.update_valve_output(l))
            flow_button.grid(row=3, column=1, padx=5, pady=5)

            # Set Valve Entry and Send Button
            move_label = tk.Label(node_frame, text="Set Flow:", font=("Arial", 10))
            move_label.grid(row=4, column=0, sticky="w", padx=5, pady=2)

            move_entry = tk.Entry(node_frame, width=10)
            move_entry.grid(row=4, column=1, padx=5, pady=2)
            move_entry.insert(0, "0")  # Initial value

            # Send Button to set valve value
            send_button = tk.Button(node_frame, text="Send", command=lambda n=node, e=move_entry: n.set_flow(e.get()))
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

            # Save reference to the frame
            self.node_frames.append(node_frame)

        # Enable Disconnect Button after connection
        self.disconnect_button.config(state=tk.NORMAL)

    def connect_device(self):
        try:
            device = propar.instrument("COM9")
            self.nodes=device.master.get_nodes()
            print(self.nodes)
            messagebox.showinfo("Connected", "Successfully connected to the device.")
            # Node 1: {'address': 4, 'type': 'DMFC', 'serial': 'M24207457D', 'id': '\x07SNM24207457D', 'channels': 1}
            if self.nodes:
                for n in range(0,len(self.nodes)):
                    node = nd.Node(self.nodes[n]["id"], f"Node_{self.nodes[n]['address']}",propar.instrument("COM9",self.nodes[n]['address']), None, None, None,None,None)
                    self.list_of_nodes.append(node)
                    # self.list_of_nodes = [node4, node5, node6, node33]
                self.update_ui_after_connection()
            else:
                messagebox.showerror("Error", "No nodes detected.")
            
        except Exception as e:
            messagebox.showerror("Error", f"Failed to connect: {e}")
            # self.nodes = [
            #     {"name": "Node A", "id": "001", "temperature": "25.0", "pressure": "1.2", "valve_output": "50%"},
            #     {"name": "Node B", "id": "002", "temperature": "24.5", "pressure": "1.3", "valve_output": "45%"},
            #     {"name": "Node C", "id": "003", "temperature": "26.0", "pressure": "1.1", "valve_output": "55%"},
            #     {"name": "Node D", "id": "004", "temperature": "25.8", "pressure": "1.4", "valve_output": "60%"}
            # ]
            # self.update_ui_after_connection()

    def disconnect_device(self):
        if self.flow_device:
            self.flow_device = None
            messagebox.showinfo("Disconnected", "Successfully disconnected from the device.")
        else:
            messagebox.showwarning("Warning", "No device connected.")
    
def main():
    root = tk.Tk()
    app = FlowControllerApp(master=root)
    root.mainloop()

if __name__ == "__main__":
    main()