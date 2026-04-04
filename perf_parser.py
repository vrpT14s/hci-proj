#!/usr/bin/env python3
# meant to be called with ```perf script -s <script name> -i <perf.data file>```

import os
from debugger import Debugger
from pprint import pp

class PerfParser:
    def __init__(self):
        #key is (dso, func_name), both can be nullable
        self.function_names = {}

        '''structure of callstacks:
        {
            command_name: [
                [(func_id, byte_offset), ...], #a singlecallstack
                ...
            ],
            ...
        }

        it's like this so it's easy to call sorted() on it
        '''
        self.callstacks = {}

    def finish_processing(self):
        print("Sorting")
        for comm in self.callstacks:
            self.callstacks[comm] = sorted(self.callstacks[comm])

        import flamegraph
        fgs = flamegraph.Flamegraphs(self.callstacks, self.function_names, executable_path=os.environ["SOURCE_EXE"])

        save_file = os.environ.get("SAVE_FILE", "flamegraphs.pickle")
        print(f"Finished processing, saving to {save_file}")

        import pickle
        with open(save_file, 'wb') as f:
            pickle.dump(fgs, f)
        print("Saved.")

    def _install_function(self, func_name):
        idx = self.function_names.get(func_name)
        if idx is None:
            idx = len(self.function_names)
            self.function_names[func_name] = idx
        return idx

    def add_sample(self, param_dict):
        #check docs.txt to see structure of param_dict
        stack = []
        for frame in param_dict['callchain'][::-1]:
            dso = frame.get('dso')
            name = frame.get('sym', {}).get('name')
            offset = frame.get('sym_off')

            stack.append((
                self._install_function((dso, name)),
                offset
            ))

        comm = param_dict['comm']
        if comm not in self.callstacks:
            self.callstacks[comm] = []
        self.callstacks[comm].append(stack)

parser = None

def trace_begin():
    global parser
    parser = PerfParser()

def process_event(param_dict):
    parser.add_sample(param_dict)

def trace_end():
    parser.finish_processing()
