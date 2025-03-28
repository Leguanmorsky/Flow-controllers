import tkinter as tk
from tkinter import messagebox, scrolledtext

class Node:
    def __init__(self, node_id, name, flow_device, temperature, pressure, valve_output,status,valve_open):
        self.node_id = node_id
        self.name = name
        self.flow_device=flow_device
        self.temperature = temperature
        self.pressure = pressure
        self.valve_output = valve_output
        self.list_of_nodes=[]
        self.status=status
        self.valve_open=valve_open

    def update_temperature(self,label):
            try:
                # params = [{'node': self.node_id,'proc_nr': 33, 'parm_nr': 7, 'parm_type': propar.PP_TYPE_INT16}]
                value = self.flow_device.readParameter(142)
                self.temperature = round(value, 6)  # Round to 3 decimal places
                label.config(text=f"Temp: {self.temperature:.6f} °C")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to update temperature: {e}")

    def update_pressure(self,label):
        try:
            # params = [{'node': self.node_id,'proc_nr': 33, 'parm_nr': 8, 'parm_type': propar.PP_TYPE_INT16}]
            value = self.flow_device.readParameter(143)
            self.pressure=round(value, 3)
            label.config(text=f"Pressure: {self.pressure:.3f} mbar")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to update pressure: {e}")

    def update_valve_output(self,label):
        try:
            # params = [{'node': self.node_id, 'proc_nr': 33, 'parm_nr': 6, 'parm_type': propar.PP_TYPE_INT16}]
            value = self.flow_device.readParameter(8)
            self.valve_output=round(value, 3)
            label.config(text=f"VolumeF: {value:.1f} ln/min")
            # {value:.4f}
            # move_entry.delete(0, tk.END)  # Clear previous value
            # move_entry.insert(0, f"{self.valve_output:.3f}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to update valve output: {e}")
    
    def update_open_valve(self,label):
        try:
            # params = [{'node': self.node_id, 'proc_nr': 33, 'parm_nr': 6, 'parm_type': propar.PP_TYPE_INT16}]
            value = self.flow_device.readParameter(234)
            self.valve_open=round(value, 3)
            label.config(text=f"valve open: {self.valve_open:.3f} %")
            # move_entry.delete(0, tk.END)  # Clear previous value
            # move_entry.insert(0, f"{self.valve_output:.3f}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to update valve open: {e}")
            
    def set_flow(self,value):
        print(value)
        try:
            
            # Try converting the value to float
            value = float(value)
            # If successful, write the value to the device
            status = self.flow_device.writeParameter(206, value)
            self.status = status
            messagebox.showinfo("Success", f"Flow set to {value:.3f} ln/min")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to set flow: {e}")
        print(self.status)
    def open_valve(self,value):
        print(value)
        try:
            
            # Try converting the value to float
            value = float(value)
            # If successful, write the value to the device
            status = self.flow_device.writeParameter(234, (value/100))
            self.status = status
            messagebox.showinfo("Success", f"Valve opened: {value:.3f} %")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to open valve: {e}")
            
# Standard mass flow in ln/min (20�C, 1.01325 bar (a)) air or g/h H2O equivalent","fbnr":22,"group0":3,"group1":"","group2":"","highly secured":False,"longname":"Standard flow",
# "max":3.40282E38,"min":-3.40282E38,"name":"NormMasFlw","parameter":253,"poll":False,"process":113,"read":True,"secured":True,"varlength":"","vartype":"f","vartype2":"","write":True},


# Nodes  Node 1: {'address': 4, 'type': 'DMFC', 'serial': 'M24207457D', 'id': '\x07SNM24207457D', 'channels': 1}


# Valve hold current/voltage at %0 setp (example: 0.8, Hold = ValveOpen * 0.8)","fbnr":28,"group0":8,"group1":"",
# "group2":"","highly secured":False,"longname":"Valve zero hold","max":1,"min":0,"name":"VlvZeroHld","parameter":234,
# "poll":False,"process":114,"read":True,"secured":True,"varlength":"","vartype":"f","vartype2":"","write":True},