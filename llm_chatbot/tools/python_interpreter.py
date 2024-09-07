import subprocess
import os
import shutil
import uuid
import json
import logging
import pexpect
import re

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

class UVPythonInterpreter:
    def __init__(self, base_dir="llm_sandbox"):
        self.base_dir = os.path.abspath(base_dir)
        self.python_version = "3.11"
        self.ensure_uv_installed()
        self.active_sessions = {}

    def ensure_uv_installed(self):
        try:
            result = subprocess.run(["uv", "--version"], check=True, capture_output=True, timeout=10, text=True)
            logger.info(f"UV version: {result.stdout.strip()}")
            return {"status": "success", "message": "uv is installed"}
        except subprocess.CalledProcessError as e:
            logger.error(f"Error checking UV: {e}")
            return {"status": "error", "message": f"uv is not installed or not working properly: {e}"}
        except subprocess.TimeoutExpired:
            logger.error("Timeout while checking UV")
            return {"status": "error", "message": "Command timed out while checking for uv"}

    def create_session(self):
        session_id = str(uuid.uuid4())
        session_dir = os.path.join(self.base_dir, session_id)

        try:
            os.makedirs(session_dir)
            logger.info(f"Created session directory: {session_dir}")

            uv_venv_cmd = f"uv venv --python={self.python_version}"
            res = subprocess.run(uv_venv_cmd, shell=True, check=True, cwd=session_dir, capture_output=True, text=True)
            logger.info(res.stdout)
            logger.info(res.stderr)
            
            venv_dir = os.path.join(session_dir, ".venv")
            activate_path = os.path.join(venv_dir, "bin", "activate")
            python_path = os.path.join(venv_dir, "bin", "python")

            child = pexpect.spawn('/bin/bash', cwd=session_dir)

            child.sendline(f"source {activate_path}")
            res = child.expect(r'.*\$')

            self.active_sessions[session_id] = {
                'process': child,
                'dir': session_dir,
                'python_path': python_path
            }

            logger.info(f"Session {session_id} created successfully")
            return {"status": "success", "session_id": session_id, "message": "Session created successfully"}
        except Exception as e:
            logger.error(f"Error creating session: {str(e)}", exc_info=True)
            if os.path.exists(session_dir):
                shutil.rmtree(session_dir)
            return {"status": "error", "message": f"Failed to create session: {str(e)}"}

    def run_command(self, session_id, command, timeout=30):
        if session_id not in self.active_sessions:
            return {"status": "error", "message": f"Session {session_id} not found"}

        child = self.active_sessions[session_id]['process']
        try:
            logger.info(f"Running command in session {session_id}: {command}")
            child.sendline(command)
            index = child.expect([pexpect.TIMEOUT, pexpect.EOF, r'.*\$'], timeout=timeout)
            
            if index == 0:
                return {"status": "error", "message": f"Command execution timed out after {timeout} seconds"}
            elif index == 1:
                return {"status": "error", "message": "Unexpected EOF while running command"}
            
            output = child.before.decode().strip()
            output_lines = output.splitlines()
            if output_lines and output_lines[0] == command:
                output = '\n'.join(output_lines[1:])
            
            logger.info(f"Command output: {output}")
            return {"status": "success", "output": output}
        except pexpect.ExceptionPexpect as e:
            logger.error(f"Pexpect error: {str(e)}", exc_info=True)
            return {"status": "error", "message": f"Command execution failed: {str(e)}"}

    def run_python_code(self, session_id, code):
        if session_id not in self.active_sessions:
            return {"status": "error", "message": f"Session {session_id} not found"}

        session_dir = self.active_sessions[session_id]['dir']
        python_path = self.active_sessions[session_id]['python_path']
        script_path = os.path.join(session_dir, "temp_script.py")

        try:
            with open(script_path, "w") as f:
                f.write(code)
            logger.info(f"Wrote code to {script_path}")

            command = f"{python_path} {script_path}"
            result = self.run_command(session_id, command)

            os.remove(script_path)
            logger.info(f"Removed temporary script: {script_path}")

            return result
        except Exception as e:
            logger.error(f"Error running code: {str(e)}", exc_info=True)
            if os.path.exists(script_path):
                os.remove(script_path)
            return {"status": "error", "message": f"Failed to run code: {str(e)}"}

    def install_package(self, session_id, package_name):
        return self.run_command(session_id, f"uv pip install {package_name}")

    def uninstall_package(self, session_id, package_name):
        return self.run_command(session_id, f"uv pip uninstall -y {package_name}")

    def list_installed_packages(self, session_id):
        result = self.run_command(session_id, "uv pip list --format=json")
        if result["status"] == "success":
            try:
                packages = json.loads(result["output"])
                return {"status": "success", "packages": packages}
            except json.JSONDecodeError:
                return {"status": "error", "message": "Failed to parse package list"}
        else:
            return result

    def get_python_version(self, session_id):
        return self.run_command(session_id, "python --version")

    def close_session(self, session_id):
        if session_id not in self.active_sessions:
            return {"status": "error", "message": f"Session {session_id} not found"}

        try:
            session = self.active_sessions[session_id]
            session['process'].close()
            shutil.rmtree(session['dir'])
            del self.active_sessions[session_id]
            logger.info(f"Session {session_id} closed and cleaned up")
            return {"status": "success", "message": f"Session {session_id} closed successfully"}
        except Exception as e:
            logger.error(f"Error closing session: {str(e)}", exc_info=True)
            return {"status": "error", "message": f"Failed to close session: {str(e)}"}

if __name__ == "__main__":
    interpreter = UVPythonInterpreter()

    # Create a new session
    result = interpreter.create_session()
    if result["status"] == "success":
        session_id = result["session_id"]
        print(f"Session created: {session_id}")

        # Run some Python code
        code_result = interpreter.run_python_code(session_id, "print('Hello, World!')\nprint(2 + 2)")
        print(f"Code execution result: {code_result}")

        # Install a package
        install_result = interpreter.install_package(session_id, "numpy")
        print(f"Package installation result: {install_result}")

        # List installed packages
        packages_result = interpreter.list_installed_packages(session_id)
        print(f"Installed packages: {packages_result}")

        # Close the session
        close_result = interpreter.close_session(session_id)
        print(f"Session close result: {close_result}")
    else:
        print(f"Failed to create session: {result['message']}")