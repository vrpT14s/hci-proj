import lldb
import os

class Debugger:
    def __init__(self):
        self.debugger = lldb.SBDebugger.Create()
        self.debugger.SetAsync(False)

        self.targets = {}

    def get_sc_list(self, dso, name):
        # Resolve kernel symbols
        if dso == '[kernel.kallsyms]':
            dso = os.environ.get('VMLINUX')
            if not dso:
                print("VMLINUX not set")
                return None

        target = self.get_target(dso)
        if not target:
            return None

        def try_find(query, name_type):
            return target.FindFunctions(query, name_type)

        # ---- 1. Try the most permissive search first ----
        sc_list = try_find(name, lldb.eFunctionNameTypeAuto)

        # ---- 2. Build fallback candidate names ----
        if sc_list.GetSize() == 0:
            candidates = []

            # Strip signature using *last* '('
            if '(' in name:
                candidates.append(name.rsplit('(', 1)[0].strip())

            # Strip template arguments
            if '<' in name:
                candidates.append(name.split('<', 1)[0].strip())

            # Strip both (common useful fallback)
            if '(' in name or '<' in name:
                base = name
                if '(' in base:
                    base = base.rsplit('(', 1)[0]
                if '<' in base:
                    base = base.split('<', 1)[0]
                candidates.append(base.strip())

            # Deduplicate while preserving order
            seen = set()
            candidates = [c for c in candidates if not (c in seen or seen.add(c))]

            # Try each candidate
            for cand in candidates:
                sc_list = try_find(cand, lldb.eFunctionNameTypeBase)
                if sc_list.GetSize() > 0:
                    break

        # ---- 3. If still nothing, give up ----
        if sc_list.GetSize() == 0:
            print(f"FAILED TO GET {(dso, name)}")
            return None
        return sc_list

    def lookup_symbol_location(self, dso, name):
        sc_list = self.get_sc_list(dso, name)
        if sc_list is None:
            return None

        for i in range(sc_list.GetSize()):
            sc = sc_list.GetContextAtIndex(i)

            func = sc.GetFunction()
            if not func.IsValid():
                continue

            start_addr = func.GetStartAddress()
            line_entry = start_addr.GetLineEntry()

            if line_entry.IsValid():
                file_spec = line_entry.GetFileSpec()
                directory = file_spec.GetDirectory()
                filename = file_spec.GetFilename()
                line = line_entry.GetLine()

                if directory and filename:
                    return f"{directory}/{filename}:{line}"

        return None

    def get_target(self, dso):
        if self.targets.get(dso) is None:
            self.targets[dso] = self.debugger.CreateTarget(dso)
        return self.targets[dso]

    def byte_to_line_histogram(self, byte_hist, dso_func_tuple):
        """
        Convert a byte offset histogram to a line offset histogram using LLDB.
        """
        line_hist = {}

        dso, function_name = dso_func_tuple
        if function_name is None:
            return

        sc_list = self.get_sc_list(dso, function_name)
        if not sc_list:
            return

        sym_ctx = sc_list[0]
        sym = sym_ctx.symbol
        if not sym or not sym.IsValid():
            return

        start_addr = sym.GetStartAddress()
        base_line_entry = start_addr.GetLineEntry()
        base_line = base_line_entry.GetLine() if base_line_entry.IsValid() else 0

        for byte_offset, count in byte_hist.items():
            addr = lldb.SBAddress(start_addr)

            if not addr.OffsetAddress(byte_offset):
                line_off = -1
            else:
                le = addr.GetLineEntry()
                line_off = le.GetLine() - base_line if le.IsValid() else -1

            line_hist[line_off] = line_hist.get(line_off, 0) + count

        return line_hist
