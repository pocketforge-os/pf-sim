import unittest
from unittest.mock import patch

from pf_sim import doctor


class DoctorTests(unittest.TestCase):
    def test_event_node_access_accepts_input_group_membership(self):
        group = type("Group", (), {"gr_gid": 123})()
        with patch.object(doctor.grp, "getgrnam", return_value=group), \
                patch.object(doctor.os, "geteuid", return_value=1000), \
                patch.object(doctor.os, "getegid", return_value=1000), \
                patch.object(doctor.os, "getgroups", return_value=[123]):
            self.assertTrue(doctor.event_node_access())

    def test_event_node_access_reports_unreadable_without_group(self):
        group = type("Group", (), {"gr_gid": 123})()
        with patch.object(doctor.grp, "getgrnam", return_value=group), \
                patch.object(doctor.os, "geteuid", return_value=1000), \
                patch.object(doctor.os, "getegid", return_value=1000), \
                patch.object(doctor.os, "getgroups", return_value=[]):
            self.assertFalse(doctor.event_node_access())


if __name__ == "__main__":
    unittest.main()
