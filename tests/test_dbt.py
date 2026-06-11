import unittest
import subprocess
import sys
from pathlib import Path

class TestDbtProject(unittest.TestCase):
    def test_dbt_compile(self):
        project_dir = Path(__file__).parent.parent / "dbt_project"
        
        # Run dbt compile
        dbt_exe = str(project_dir.parent / "venv" / "Scripts" / "dbt.exe")
        if not Path(dbt_exe).exists():
            dbt_exe = "dbt"  # Fallback to path

        cmd = [
            dbt_exe, "compile",
            "--project-dir", str(project_dir),
            "--profiles-dir", str(project_dir)
        ]
        
        res = subprocess.run(cmd, cwd=str(project_dir), capture_output=True, text=True)
        print("dbt compile stdout:", res.stdout)
        print("dbt compile stderr:", res.stderr)
        
        self.assertEqual(res.returncode, 0, f"dbt compile failed: {res.stderr}")

if __name__ == "__main__":
    unittest.main()
