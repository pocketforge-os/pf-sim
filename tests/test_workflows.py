import unittest
from pathlib import Path


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.workflows = Path(__file__).resolve().parents[1] / ".github" / "workflows"

    def test_reusable_workflow_checks_out_pf_sim_at_selected_ref(self):
        workflow = self.workflows / "pf-sim-scenarios.yml"
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

    def test_job_level_env_does_not_use_step_only_contexts(self):
        for workflow_name in ("ci.yml", "pf-sim-scenarios.yml"):
            lines = (self.workflows / workflow_name).read_text().splitlines()
            in_jobs = False
            job_indent = None
            env_indent = None

            for line in lines:
                stripped = line.strip()
                indent = len(line) - len(line.lstrip())
                if stripped == "jobs:":
                    in_jobs = True
                    continue
                if not in_jobs or not stripped or stripped.startswith("#"):
                    continue
                if indent == 2 and stripped.endswith(":"):
                    job_indent = indent
                    env_indent = None
                    continue
                if job_indent is not None and indent == job_indent + 2 and stripped == "env:":
                    env_indent = indent
                    continue
                if env_indent is not None:
                    if indent <= env_indent:
                        env_indent = None
                    else:
                        self.assertNotIn("runner.", line, workflow_name)
                        self.assertNotIn("steps.", line, workflow_name)


if __name__ == "__main__":
    unittest.main()
