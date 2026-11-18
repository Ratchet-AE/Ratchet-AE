"""DUT integration skeleton: translate model responses to executable stimulus."""
from ratchet.dut_api import DUTAdapter


class Adapter(DUTAdapter):
    """Implement stimulus handling for the new DUT."""

    def candidates(self, response, level):
        """Return candidate segments from a model response."""
        raise NotImplementedError

    def check_prefix(self, units, index):
        """Validate a checkpoint cut in a sequence of units."""
        raise NotImplementedError

    def primitives(self, stimulus):
        """Return the units making up an executable stimulus."""
        raise NotImplementedError

    def build_stimulus(self, candidate):
        """Translate a model candidate into a stimulus."""
        raise NotImplementedError

    def splice_prefix(self, prefix, stimulus):
        """Join the frozen prefix to the candidate stimulus."""
        raise NotImplementedError

    def exempt_self_induced_exception(self, clear_event, target_event):
        """Return whether a target-induced exception is exempt."""
        return False

    def key_state_registers(self, state=None):
        """Select state fields included in the prefix summary."""
        return ()
