# vcs_handler.py

import subprocess
import logging
from datetime import datetime

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def run_command(command, cwd):
    """
    Executes a shell command and logs its output.
    """
    try:
        process = subprocess.Popen(command, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
        stdout, stderr = process.communicate()

        if process.returncode == 0:
            logging.info(f"Successfully executed: {' '.join(command)}")
            if stdout:
                logging.info(stdout.decode('utf-8'))
        else:
            logging.error(f"Error executing: {' '.join(command)}")
            if stderr:
                logging.error(stderr.decode('utf-8'))
        
        return process.returncode == 0
    except Exception as e:
        logging.error(f"Exception while running command {' '.join(command)}: {e}")
        return False

import config

def push_to_github():
    """
    Adds, commits, and pushes changes to the GitHub repository.
    """
    vcs_conf = config.VCS_CONFIG
    repo_path = vcs_conf['REPO_PATH']
    
    logging.info(f"Starting Git operations in repository: {repo_path}")

    # 1. Git Add
    if not run_command(['git', 'add', '.'], cwd=repo_path):
        logging.error("Failed to add files to git.")
        return False

    # 2. Git Commit
    commit_message = f"Automated report and log update for {datetime.now().strftime('%Y-%m-%d')}"
    if not run_command(['git', 'commit', '-m', f'"{commit_message}"'], cwd=repo_path):
        # This might fail if there are no changes to commit, which is not a critical error.
        logging.warning("Git commit failed. This might be because there are no new changes to commit.")
        # We can proceed to push anyway, in case there are previous unpushed commits.
    
    # 3. Git Push
    remote = vcs_conf['REMOTE_NAME']
    branch = vcs_conf['BRANCH_NAME']
    if not run_command(['git', 'push', remote, branch], cwd=repo_path):
        logging.error("Failed to push changes to GitHub.")
        return False

    logging.info("Successfully pushed changes to GitHub.")
    return True

if __name__ == '__main__':
    # Example Usage (requires a dummy config and a git repo)
    class DummyConfig:
        VCS_CONFIG = {
            "REPO_PATH": ".",  # Assumes the script is run from the repo root
            "REMOTE_NAME": "origin",
            "BRANCH_NAME": "main"
        }

    print("--- Testing Git Push (will fail if not in a git repo or no remote is configured) ---")
    # To test this properly:
    # 1. `git init` in the current directory
    # 2. Create a file: `echo "test" > test.txt`
    # 3. `git add .` and `git commit -m "Initial"`
    # 4. Configure a remote: `git remote add origin <your-repo-url>`
    # 5. Then run this script.
    push_to_github(DummyConfig)