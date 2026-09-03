import unittest
from unittest.mock import Mock, patch

from pf_sim import doctor


class DoctorTests(unittest.TestCase):
    def test_event_node_access_probes_created_node(self):
        device = Mock(sysname="input123")
        codes = [304, 305, 307, 308, 310, 311, 312, 313, 314, 315, 316]
        with patch.object(doctor.os, "access", return_value=True), \
                patch.object(doctor, "contract_codes", return_value=codes) as contract, \
                patch.object(doctor, "UInputDevice", return_value=device) as create, \
                patch.object(doctor, "find_event_node", return_value="/dev/input/event17") as find, \
                patch.object(doctor, "wait_event_node_readable", return_value=True) as readable:
            self.assertEqual(doctor.event_node_access(), "ok")
        contract.assert_called_once_with()
        create.assert_called_once_with(codes, "doctor-probe")
        find.assert_called_once_with("input123")
        readable.assert_called_once_with("/dev/input/event17")
        device.close.assert_called_once_with()

    def test_event_node_access_reports_unreadable_probe(self):
        device = Mock(sysname="input123")
        with patch.object(doctor.os, "access", return_value=True), \
                patch.object(doctor, "UInputDevice", return_value=device), \
                patch.object(doctor, "find_event_node", return_value="/dev/input/event17"), \
                patch.object(doctor, "wait_event_node_readable", return_value=False):
            self.assertEqual(doctor.event_node_access(), "unreadable")
        device.close.assert_called_once_with()

    def test_event_node_access_is_unknown_without_uinput(self):
        with patch.object(doctor.os, "access", return_value=False), \
                patch.object(doctor, "UInputDevice") as create:
            self.assertEqual(doctor.event_node_access(), "unknown")
        create.assert_not_called()


if __name__ == "__main__":
    unittest.main()
