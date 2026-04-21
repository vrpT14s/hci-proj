from flamegraph import *
from collections import defaultdict

class FolderTree:
    class Inode:
        __slots__ = ('children', 'area')
        def __init__(self):
            self.children = set()
            self.area = 0
        def add_child(self, child):
            self.children.add(child)
        def add_area(self, area):
            self.area += area

    def __init__(self, fg, root):
        self.fg = fg
        self.rebuild(root)

    def get_pathfunc(self, sample_rect: FlameNode):
        pathline = self.fg.node_path(sample_rect)
        if pathline is None:
            return None
        return pathline[0] / self.fg.node_display_name(sample_rect)

    def rebuild(self, root: FlameNode):
        self.inodes = self.build_folder_tree(root)

    def build_folder_tree(self, root_sample: FlameNode):
        inodes = defaultdict(self.Inode)

        def dfs(sample_rect: FlameNode):
            path = self.get_pathfunc(sample_rect)
            area = sample_rect.total()
            if path is not None:
                for i, parent in enumerate(path.parents[::-1]):
                    inodes[str(parent)].add_area(area)
                    inodes[str(parent)].add_child(path.parts[i+1])
                inodes[str(path)].add_area(area)

            for child_node in sample_rect.children.values():
                dfs(child_node)

        dfs(root_sample)
        return inodes

    #we want top k (by area) nodes of the tree such that no node is an ancestor of another
    #so there's a nice equal coloring of the flamegraph
    def top_independent_paths(self, k=10, inodes=None):
        """
        Finds a non-ancestral frontier of size k using a Balanced Shatter heuristic.
        Returns a list of strings representing the discovered paths.
        """
        if inodes is None:
            inodes = self.inodes

        if not inodes:
            return []

        # --- GRAPH HELPERS ---
        def get_children_paths(parent_path):
            """Safely construct and verify child paths from the Inode graph."""
            paths = []
            for child_name in inodes[parent_path].children:
                child_path = str(Path(parent_path) / child_name)
                if child_path in inodes:
                    paths.append(child_path)
            return paths

        def get_shatter_score(path):
            node = inodes[path]
            children_paths = get_children_paths(path)

            if not children_paths:
                return 0.0

            # If there's only one child, the dominance is 100%,
            # but we SHOULD shatter it anyway to get deeper into the tree.
            if len(children_paths) == 1:
                return node.area * 2  # Give it a "pity score" so it stays in the queue

            max_child_area = max(inodes[cp].area for cp in children_paths)
            dominance_ratio = max_child_area / node.area

            # Standard heuristic for branching nodes
            return node.area * (1.0 - dominance_ratio)

        # --- PHASE 1: INITIALIZATION ---
        # Find all absolute roots (nodes with no valid parents in the graph)
        frontier = set()
        for path in inodes.keys():
            parent_path = str(Path(path).parent)
            if parent_path not in inodes or parent_path == path:
                frontier.add(path)

        # --- PHASE 2: PRIORITY QUEUE SETUP ---
        # Max-heap storing tuples of: (-shatter_score, -area, path)
        # Area is included as a tie-breaker to prioritize heavier nodes
        pq = []
        for path in frontier:
            score = get_shatter_score(path)
            heapq.heappush(pq, (-score, -inodes[path].area, path))

        # --- PHASE 3: GREEDY FRONTIER EXPANSION ---
        while len(frontier) < k and pq:
            neg_score, neg_area, parent_path = pq[0]

            # If the highest score is 0, all remaining nodes are either leaves
            # or completely monolithic. Expanding further is useless.
            if neg_score == 0:
                break

            # Pop the target and "shatter" it
            heapq.heappop(pq)
            frontier.remove(parent_path)

            children_paths = get_children_paths(parent_path)
            for child_path in children_paths:
                frontier.add(child_path)

                # Score the newly exposed nodes and add them to the queue
                score = get_shatter_score(child_path)
                heapq.heappush(pq, (-score, -inodes[child_path].area, child_path))

        # --- PHASE 4: FINAL SELECTION ---
        # Shattering might cause the frontier to slightly exceed 'k'.
        # We return exactly the 'k' heaviest nodes from the resulting cut.
        final_nodes = sorted(
            list(frontier),
            key=lambda p: inodes[p].area,
            reverse=True
        )

        return final_nodes[:k]
