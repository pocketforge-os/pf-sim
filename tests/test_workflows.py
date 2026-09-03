import unittest
from pathlib import Path


class WorkflowTests(unittest.TestCase):
    def test_reusable_workflow_checks_out_pf_sim_at_selected_ref(self):
        workflow = (Path(__file__).resolve().parents[1] / ".github" / "workflows" /
                    "pf-sim-scenarios.yml")
        lines = workflow.read_text().splitlines()

        checkout = next(index for index, line in enumerate(lines)
                        if line.strip().startswith("uses: actions/checkout@"))
        step_indent = len(lines[checkout]) - len(lines[checkout].lstrip())
        step = []
        for line in lines[checkout + 1:]:
            indent = len(line) - len(line.lstrip())
            if line.strip().startswith("- ") and indent < step_indent:
                break
            step.append(line.strip())

        self.assertIn("with:", step)
        self.assertIn("repository: pocketforge-os/pf-sim", step)
        self.assertIn("ref: ${{ inputs.pf_sim_ref || github.sha }}", step)


if __name__ == "__main__":
    unittest.main()
