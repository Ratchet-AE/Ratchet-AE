"""Load DUT configuration and define the stimulus and diagnostic interfaces."""
from importlib import import_module
from pathlib import Path
import json
import re
from .paths import DUT_DIR


class DUTAdapter:
    """Define operations supplied by a DUT integration."""
    def __init__(self, config=None, root=None):
        self.config = config or {}
        self.root = Path(root) if root is not None else Path.cwd()
        self.name = self.root.name if root is not None else None

    def candidates(self, response, level):
        raise NotImplementedError('The DUT adapter must provide candidate extraction')

    def check_prefix(self, units, index):
        raise NotImplementedError('The DUT adapter must provide prefix validation')

    def candidate_fragment(self, candidate):
        return candidate['suffix']

    def primitives(self, stimulus):
        raise NotImplementedError('The DUT adapter must provide primitive extraction')

    def build_stimulus(self, candidate):
        raise NotImplementedError('The DUT adapter must provide stimulus construction')

    def splice_prefix(self, prefix, stimulus):
        raise NotImplementedError('The DUT adapter must provide prefix composition')

    def count_instructions(self, fragment):
        return int(bool(fragment.strip()))

    def exempt_self_induced_exception(self, clear_event, target_event):
        return False

    def key_state_registers(self, state=None):
        return ()

    def support_components(self):
        """Return optional DUT-specific policy, archive and replay components."""
        return {}

    def read_trace(self, output, stimulus):
        """Read DUT-specific trace data for a stimulus."""
        raise NotImplementedError('The DUT adapter must provide trace reading')


def load_dut(name):
    """Return the DUT description and an adapter instance for a local DUT name."""
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*', name):
        raise ValueError('Invalid DUT name')
    root = DUT_DIR(name)
    config = json.loads((root / 'dut.yaml').read_text())
    adapter = import_module('tb.' + name + '.adapter').Adapter(config, root)
    if not isinstance(adapter, DUTAdapter):
        raise TypeError('DUT adapter must inherit DUTAdapter')
    return config, adapter
