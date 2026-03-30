import lldb

class Debugger:
    def __init__(self, executable):
        # Initialize LLDB debugger
        self.debugger = lldb.SBDebugger.Create()
        self.debugger.SetAsync(False)

        # Create a target from executable
        self.target = self.debugger.CreateTarget(executable)
        if not self.target or not self.target.IsValid():
            raise RuntimeError(f"Failed to create target for {executable}")

    def list_function(self, func_name, num_lines=50):
        # Find functions by name
        funcs = self.target.FindFunctions(func_name)

        if funcs.GetSize() == 0:
            print(f"Function '{func_name}' not found")
            return

        # for now, just take the first function that matches that name
        func = funcs.GetContextAtIndex(0).GetFunction()
        if not func or not func.IsValid():
            print(f"Invalid function for '{func_name}'")
            return

        # Get start line entry
        start_addr = func.GetStartAddress()
        line_entry = start_addr.GetLineEntry()

        if not line_entry.IsValid():
            print(f"No debug line info for '{func_name}'")
            return

        file_spec = line_entry.GetFileSpec()
        line_no = line_entry.GetLine()

        file_path = file_spec.fullpath
        if not file_path:
            print("No file path available")
            return

        # Read file and print lines
        try:
            with open(file_path, "r") as f:
                lines = f.readlines()
        except Exception as e:
            print(f"Failed to read source file: {e}")
            return

        start = max(0, line_no - 1)
        end = min(len(lines), start + num_lines)

        text = ""
        for i in range(max(start-5, 0), end):
            text += f"{i+1:5d}: {lines[i].rstrip()}\n"
        #text += "</code></pre>"
        return text
