try:
    import lldb
except ImportError:
    lldb = None

class Debugger:
    def __init__(self, executable):
        self.available = lldb is not None
        self.executable = executable

        if not self.available:
            self.debugger = None
            self.target = None
            print("Warning: LLDB Python module not available. Symbol/line resolution disabled.")
            return

        # Initialize LLDB debugger
        self.debugger = lldb.SBDebugger.Create()
        self.debugger.SetAsync(False)

        # Create a target from executable
        self.target = self.debugger.CreateTarget(executable)
        if not self.target or not self.target.IsValid():
            raise RuntimeError(f"Failed to create target for {executable}")

    def lookup_symbol_location(self, name):
        """
        Resolve a perf symbol name to 'file:line' using LLDB.
        Returns None if not found.
        """
        if not self.available:
            return None

        # 1. Try direct symbol lookup (best for perf)
        symbols = self.target.FindSymbols(name)

        if symbols.GetSize() == 0:
            # fallback: try function lookup
            symbols = self.target.FindFunctions(name)

            if symbols.GetSize() == 0:
                return None

        sym_ctx = symbols.GetContextAtIndex(0)

        # Prefer function, fallback to symbol
        obj = sym_ctx.GetFunction() or sym_ctx.GetSymbol()
        if not obj:
            return None

        addr = obj.GetStartAddress()
        line_entry = addr.GetLineEntry()

        if not line_entry.IsValid():
            return None

        file_spec = line_entry.GetFileSpec()
        directory = file_spec.GetDirectory()
        filename = file_spec.GetFilename()
        line = line_entry.GetLine()

        if filename is None:
            return None

        full_path = f"{directory}/{filename}" if directory else filename
        return f"{full_path}:{line}"

    def resolve_addr(self, ip):
        if not self.available:
            return None, None
        #addr = self.target.ResolveLoadAddress(ip)
        addr = self.target.modules[0].ResolveFileAddress(ip)
        assert len(self.target.modules) == 1
        #if random.randint(0, 10005) == 10000:
        #    breakpoint()
        #print(addr, addr.GetFunction())
        #breakpoint()
        print(addr)
        return addr.GetFunction().name, 10
    def byte_to_line_histogram(self, byte_hist, function_name):
        """
        Convert a byte offset histogram to a line offset histogram using LLDB.
        Uses modern LLDB Python API: SBSymbolContext -> SBSymbol -> SBAddress.
        """
        if not self.available:
            return {}

        target = self.target
        line_hist = {}

        # 1️⃣ Find the function symbol
        symbol_list = target.FindFunctions(function_name)
        if symbol_list.GetSize() == 0:
            raise ValueError(f"Function '{function_name}' not found in target modules.")

        sym_ctx = symbol_list.GetContextAtIndex(0)
        sym = sym_ctx.symbol
        if not sym.IsValid():
            raise ValueError(f"Symbol for function '{function_name}' is invalid.")

        # 2️⃣ Get function start address
        start_addr = sym.GetStartAddress()
        base_line_entry = start_addr.GetLineEntry()
        base_line = base_line_entry.GetLine() if base_line_entry.IsValid() else 0

        # 3️⃣ Map each byte offset to its corresponding line
        for byte_offset, count in byte_hist.items():
            # Create a copy of the start address for this offset
            addr = lldb.SBAddress(start_addr)
            if not addr.OffsetAddress(byte_offset):
                # fallback: treat as unknown line
                line_off = -1
            else:
                le = addr.GetLineEntry()
                line_off = le.GetLine() - base_line if le.IsValid() else -1

            line_hist[line_off] = line_hist.get(line_off, 0) + count

        return line_hist
