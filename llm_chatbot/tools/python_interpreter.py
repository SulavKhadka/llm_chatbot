import subprocess
import os
import shutil
import uuid
import json
import logging
import time
import select
from typing import Dict, Any, Optional

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class UVPythonShellManager:
    """
    Manages Python virtual environments using the UV package manager.

    This class provides methods to create, manage, and interact with isolated Python
    environments. It uses the UV package manager for faster dependency resolution and
    installation. The manager allows creating multiple sessions, each with its own
    virtual environment, and provides methods to run Python code, install packages,
    and manage the lifecycle of these environments.

    Attributes:
        base_dir (str): The base directory where all session directories will be created.
        python_version (str): The version of Python to use for virtual environments.
        active_sessions (Dict[str, Dict[str, Any]]): A dictionary storing information about active sessions.
        curr_session_id (str): The ID of the current active session.

    Note:
        This class requires the UV package manager to be installed on the system.
        It's designed to work with Python 3.11 by default.
    """
    def __init__(self, base_dir: str = "llm_sandbox"):
        self.base_dir = os.path.abspath(base_dir)
        self.python_version = "3.11"
        self.active_sessions: Dict[str, Dict[str, Any]] = {}
        self.curr_session_id = None

    def create_session(self) -> Dict[str, str]:
        """
        Creates a new Python virtual environment session.

        This method sets up a new isolated Python environment using UV. It creates
        a unique directory for the session, installs Python 3.11 if not already 
        available, and sets up a virtual environment. This is the first method you 
        should call before running any Python code or installing packages.

        Returns:
            Dict[str, str]: A dictionary containing information about the created session.
                The dictionary has the following keys:
                - 'status': 'success' if the session was created, 'error' otherwise.
                - 'session_id': A unique identifier for the created session (only if successful).
                - 'message': A description of the result or error message.

        Note:
            - Each session is isolated from others and from the system Python installation.
            - The method automatically sets the created session as the current active session.
            - If an error occurs during session creation, any partially created directories
              will be cleaned up.
        """
        session_id = str(uuid.uuid4())
        session_dir = os.path.join(self.base_dir, session_id)

        try:
            os.makedirs(session_dir)
            logger.info(f"Created session directory: {session_dir}")

            venv_dir = os.path.join(session_dir, ".venv")
            python_path = os.path.join(venv_dir, "bin", "python")

            process = subprocess.Popen(
                ["/bin/bash"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                cwd=session_dir
            )

            with open(f"{session_dir}/tmp_uv_setup_script.sh", "w") as file:
                file.write('''#!/bin/bash

# Exit immediately if a command exits with a non-zero status
set -e

# Function to check if a command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

echo "Initial Python version:"
which python

# Check if uv is installed
if ! command_exists uv; then
    echo "uv is not installed. Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    source $HOME/.cargo/env
else
    echo "uv is already installed. Version: $(uv --version)"
fi

# Install Python 3.11 using uv if not already installed
if ! command_exists python3.11; then
    echo "Installing Python 3.11..."
    uv python install 3.11
else
    echo "Python 3.11 is already installed."
fi

# Check if .venv directory exists
if [ ! -d ".venv" ]; then
    echo "Creating a new virtual environment..."
    uv venv --python=3.11
else
    echo "Virtual environment already exists."
fi

# Activate the virtual environment
echo "Activating the virtual environment..."
source .venv/bin/activate

# Verify Python version
echo "Python version:"
which python

echo "Setup complete. The virtual environment is now activated."
echo "To deactivate the environment, run 'deactivate'."
echo "To activate it again later, run 'source .venv/bin/activate' from the llm_chatbot directory."''')

            logger.info("ensuring uv is installed")
            setup_cmd_output = self.execute_command(process, f"/bin/bash {session_dir}/tmp_uv_setup_script.sh", timeout=30)

            self.curr_session_id = session_id
            self.active_sessions[session_id] = {
                'process': process,
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

    def execute_command(self, process: subprocess.Popen, command: str, timeout: float = 30.0) -> Dict[str, str]:
        """
        Executes a shell command in the context of a given process.

        This method is used internally to run commands within a specific session's
        environment. It handles command execution, output capturing, and timeout 
        management.

        Args:
            process (subprocess.Popen): The subprocess representing the session's shell.
            command (str): The command to execute in the shell.
            timeout (float, optional): Maximum time in seconds to wait for the command 
                to complete. Defaults to 30.0 seconds.

        Returns:
            Dict[str, str]: A dictionary containing the result of the command execution.
                The dictionary has the following keys:
                - 'status': 'success' if the command executed successfully, 'error' otherwise.
                - 'stdout': The standard output of the command (only if successful).
                - 'stderr': The standard error output of the command (only if successful).
                - 'message': A description of the error (only if an error occurred).

        Note:
            - This method is not intended to be called directly by users of the class.
            - It uses a unique end marker to reliably capture the command's output.
            - If the command doesn't complete within the specified timeout, it will 
              return an error status.
        """
        try:
            process.stdin.write(f"{command}\n")
            process.stdin.flush()

            stdout_output, stderr_output = [], []
            
            end_marker = f"__END_OF_COMMAND_{os.urandom(8).hex()}__"
            process.stdin.write(f"echo {end_marker}\n")
            process.stdin.flush()

            poller = select.poll()
            poller.register(process.stdout, select.POLLIN)
            poller.register(process.stderr, select.POLLIN)

            end_time = time.time() + timeout
            while time.time() < end_time:
                ready = poller.poll(0.1)
                for fd, event in ready:
                    if event & select.POLLIN:
                        if fd == process.stdout.fileno():
                            line = process.stdout.readline().strip()
                            if line == end_marker:
                                return {"status": "success", "stdout": '\n'.join(stdout_output), "stderr": '\n'.join(stderr_output)}
                            stdout_output.append(line)
                            logger.info(f"STDOUT: {line}")
                        elif fd == process.stderr.fileno():
                            line = process.stderr.readline().strip()
                            stderr_output.append(line)
                            logger.error(f"STDERR: {line}")

            logger.warning(f"Command execution timed out after {timeout} seconds")
            return {"status": "error", "message": f"Command timed out after {timeout} seconds"}

        except Exception as e:
            logger.error(f"Error executing command: {e}")
            return {"status": "error", "message": str(e)}

    def run_command(self, command: str, session_id: str = None, timeout: float = 30.0) -> Dict[str, str]:
        """
        Runs a shell command in the context of a specific session.

        This method allows execution of arbitrary shell commands within the 
        environment of a given session. It's useful for running system commands
        or scripts that are not direct Python code.

        Args:
            command (str): The shell command to execute.
            session_id (str, optional): The ID of the session in which to run the command. 
                If None, uses the current active session. Defaults to None.
            timeout (float, optional): Maximum time in seconds to wait for the command 
                to complete. Defaults to 30.0 seconds.

        Returns:
            Dict[str, str]: A dictionary containing the result of the command execution.
                The dictionary has the following keys:
                - 'status': 'success' if the command executed successfully, 'error' otherwise.
                - 'stdout': The standard output of the command (only if successful).
                - 'stderr': The standard error output of the command (only if successful).
                - 'message': A description of the error (only if an error occurred).

        Note:
            - This method activates the virtual environment of the specified session
              before running the command.
            - Be cautious when running shell commands, as they have full access to 
              the system within the constraints of the virtual environment.
        """
        session_id = self.curr_session_id if session_id is None else session_id
        if session_id not in self.active_sessions:
            return {"status": "error", "message": f"Session {session_id} not found"}

        process = self.active_sessions[session_id]['process']
        return self.execute_command(process, command, timeout)

    def run_python_code(self, code: str, session_id: str = None) -> Dict[str, str]:
        """
        Executes Python code within a specific session's environment.

        This method allows running arbitrary Python code in the context of a 
        virtual environment session. It's useful for testing code snippets,
        running scripts, or interacting with installed packages.

        Args:
            code (str): The Python code to execute. Can be a single line or 
                multiple lines of code.
            session_id (str, optional): The ID of the session in which to run the code. 
                If None, uses the current active session. Defaults to None.

        Returns:
            Dict[str, str]: A dictionary containing the result of the code execution.
                The dictionary has the following keys:
                - 'status': 'success' if the code executed successfully, 'error' otherwise.
                - 'stdout': The standard output of the code execution (only if successful).
                - 'stderr': The standard error output (only if successful).
                - 'message': A description of the error (only if an error occurred).

        Note:
            - The code is executed in the isolated environment of the specified session,
              with access only to the packages installed in that environment.
            - The method creates a temporary Python script file, executes it, and then
              removes the file.
            - Be cautious with code that may have side effects or security implications.
        """
        session_id = self.curr_session_id if session_id is None else session_id
        if session_id not in self.active_sessions:
            return {"status": "error", "message": f"Session {session_id} not found"}

        session = self.active_sessions[session_id]
        script_path = os.path.join(session['dir'], "temp_script.py")

        try:
            with open(script_path, "w") as f:
                f.write(code)
            logger.info(f"Wrote code to {script_path}")

            result = self.run_command(session_id, f"python {script_path}")

            os.remove(script_path)
            logger.info(f"Removed temporary script: {script_path}")

            return result
        except Exception as e:
            logger.error(f"Error running code: {str(e)}", exc_info=True)
            if os.path.exists(script_path):
                os.remove(script_path)
            return {"status": "error", "message": f"Failed to run code: {str(e)}"}

    def install_package(self, package_name: str, session_id: str = None) -> Dict[str, str]:
        """
        Installs a Python package in a specific session using UV.

        This method uses the UV package manager to install a Python package
        within the virtual environment of a given session. It's faster and more
        efficient than traditional pip installations.

        Args:
            package_name (str): The name of the package to install. Can include version
                specifiers (e.g., 'numpy==1.21.0').
            session_id (str, optional): The ID of the session in which to install the package. 
                If None, uses the current active session. Defaults to None.

        Returns:
            Dict[str, str]: A dictionary containing the result of the package installation.
                The dictionary has the following keys:
                - 'status': 'success' if the package was installed successfully, 'error' otherwise.
                - 'stdout': The standard output of the installation process (only if successful).
                - 'stderr': The standard error output (only if successful).
                - 'message': A description of the error (only if an error occurred).

        Note:
            - This method is preferred over using pip directly within the session.
            - Package installation is isolated to the specified session and doesn't
              affect other sessions or the system Python installation.
            - Dependencies of the specified package are also installed automatically.
        """
        session_id = self.curr_session_id if session_id is None else session_id
        if session_id not in self.active_sessions:
            return {"status": "error", "message": f"Session {session_id} not found"}
        
        return self.run_command(session_id, f"uv pip install {package_name}")

    def uninstall_package(self, package_name: str, session_id: str = None) -> Dict[str, str]:
        """
        Uninstalls a Python package from a specific session using UV.

        This method removes a previously installed package from the virtual 
        environment of a given session. It uses UV for efficient package management.

        Args:
            package_name (str): The name of the package to uninstall.
            session_id (str, optional): The ID of the session from which to uninstall the package. 
                If None, uses the current active session. Defaults to None.

        Returns:
            Dict[str, str]: A dictionary containing the result of the package uninstallation.
                The dictionary has the following keys:
                - 'status': 'success' if the package was uninstalled successfully, 'error' otherwise.
                - 'stdout': The standard output of the uninstallation process (only if successful).
                - 'stderr': The standard error output (only if successful).
                - 'message': A description of the error (only if an error occurred).

        Note:
            - This method only affects the specified session and doesn't impact
              other sessions or the system Python installation.
            - It uses the '-y' flag to automatically confirm the uninstallation without
              user interaction.
            - Be cautious when uninstalling packages that other installed packages 
              might depend on.
        """
        session_id = self.curr_session_id if session_id is None else session_id
        if session_id not in self.active_sessions:
            return {"status": "error", "message": f"Session {session_id} not found"}
        
        return self.run_command(session_id, f"uv pip uninstall -y {package_name}")

    def close_session(self, session_id: str = None) -> Dict[str, str]:
        """
        Closes and cleans up a specific session.

        This method terminates the session's processes, removes the associated
        virtual environment, and cleans up all related files and directories.

        Args:
            session_id (str, optional): The ID of the session to close. 
                If None, closes the current active session. Defaults to None.

        Returns:
            Dict[str, str]: A dictionary containing the result of the session closure.
                The dictionary has the following keys:
                - 'status': 'success' if the session was closed successfully, 'error' otherwise.
                - 'message': A description of the result or error message.

        Note:
            - This method should be called when a session is no longer needed to free up 
              system resources and storage space.
            - After closing a session, it cannot be reopened. A new session must be created
              if further operations are needed.
            - Ensure all important data or results from the session are saved before closing,
              as all session-specific data will be permanently deleted.
        """
        session_id = self.curr_session_id if session_id is None else session_id
        if session_id not in self.active_sessions:
            return {"status": "error", "message": f"Session {session_id} not found"}
        
        if session_id not in self.active_sessions:
            return {"status": "error", "message": f"Session {session_id} not found"}

        try:
            session = self.active_sessions[session_id]
            session['process'].terminate()
            session['process'].wait(timeout=5)
            shutil.rmtree(session['dir'])
            del self.active_sessions[session_id]
            logger.info(f"Session {session_id} closed and cleaned up")
            return {"status": "success", "message": f"Session {session_id} closed successfully"}
        except Exception as e:
            logger.error(f"Error closing session: {str(e)}", exc_info=True)
            return {"status": "error", "message": f"Failed to close session: {str(e)}"}

if __name__ == "__main__":
    manager = UVPythonShellManager()

    # Create a new session
    result = manager.create_session()
    if result["status"] == "success":
        session_id = result["session_id"]
        print(f"Session created: {session_id}")

        # Run some Python code
        code_result = manager.run_python_code(session_id, "print('Hello, World!')\nprint(2 + 2)")
        print(f"Code execution result: {code_result}")

        # Install a package
        install_result = manager.install_package(session_id, "numpy")
        print(f"Package installation result: {install_result}")

        # List installed packages
        packages_result = manager.list_installed_packages(session_id)
        print(f"Installed packages: {packages_result}")

        # Close the session
        close_result = manager.close_session(session_id)
        print(f"Session close result: {close_result}")
    else:
        print(f"Failed to create session: {result['message']}")


    def create_session(self) -> Dict[str, str]:
        session_id = str(uuid.uuid4())
        session_dir = os.path.join(self.base_dir, session_id)

        try:
            os.makedirs(session_dir)
            logger.info(f"Created session directory: {session_dir}")



            self.active_sessions[session_id] = {
                'process': process,
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

    def run_command(self, session_id: str, command: str, timeout: float = 30.0) -> Dict[str, str]:
        if session_id not in self.active_sessions:
            return {"status": "error", "message": f"Session {session_id} not found"}

        session = self.active_sessions[session_id]
        activate_cmd = f"source {session['activate_path']} && {command}"
        return self.execute_command(["bash", "-c", activate_cmd], cwd=session['dir'], timeout=timeout)

    def run_python_code(self, session_id: str, code: str) -> Dict[str, str]:
        if session_id not in self.active_sessions:
            return {"status": "error", "message": f"Session {session_id} not found"}

        session = self.active_sessions[session_id]
        script_path = os.path.join(session['dir'], "temp_script.py")

        try:
            with open(script_path, "w") as f:
                f.write(code)
            logger.info(f"Wrote code to {script_path}")

            result = self.run_command(session_id, f"{session['python_path']} {script_path}")

            os.remove(script_path)
            logger.info(f"Removed temporary script: {script_path}")

            return result
        except Exception as e:
            logger.error(f"Error running code: {str(e)}", exc_info=True)
            if os.path.exists(script_path):
                os.remove(script_path)
            return {"status": "error", "message": f"Failed to run code: {str(e)}"}

    def install_package(self, session_id: str, package_name: str) -> Dict[str, str]:
        return self.run_command(session_id, f"uv pip install {package_name}")

    def uninstall_package(self, session_id: str, package_name: str) -> Dict[str, str]:
        return self.run_command(session_id, f"uv pip uninstall -y {package_name}")

    def list_installed_packages(self, session_id: str) -> Dict[str, Any]:
        result = self.run_command(session_id, "uv pip list --format=json")
        if result["status"] == "success":
            try:
                packages = json.loads(result["stdout"])
                return {"status": "success", "packages": packages}
            except json.JSONDecodeError:
                return {"status": "error", "message": "Failed to parse package list"}
        else:
            return result

    def get_python_version(self, session_id: str) -> Dict[str, str]:
        return self.run_command(session_id, "python --version")

    def close_session(self, session_id: str) -> Dict[str, str]:
        if session_id not in self.active_sessions:
            return {"status": "error", "message": f"Session {session_id} not found"}

        try:
            session = self.active_sessions[session_id]
            shutil.rmtree(session['dir'])
            del self.active_sessions[session_id]
            logger.info(f"Session {session_id} closed and cleaned up")
            return {"status": "success", "message": f"Session {session_id} closed successfully"}
        except Exception as e:
            logger.error(f"Error closing session: {str(e)}", exc_info=True)
            return {"status": "error", "message": f"Failed to close session: {str(e)}"}

if __name__ == "__main__":
    manager = UVPythonShellManager()

    # Create a new session
    result = manager.create_session()
    if result["status"] == "success":
        session_id = result["session_id"]
        print(f"Session created: {session_id}")

        # Run some Python code
        code_result = manager.run_python_code(session_id, "print('Hello, World!')\nprint(2 + 2)")
        print(f"Code execution result: {code_result}")

        # Install a package
        install_result = manager.install_package(session_id, "numpy")
        print(f"Package installation result: {install_result}")

        # List installed packages
        packages_result = manager.list_installed_packages(session_id)
        print(f"Installed packages: {packages_result}")

        # Close the session
        close_result = manager.close_session(session_id)
        print(f"Session close result: {close_result}")
    else:
        print(f"Failed to create session: {result['message']}")