import os
import sys
import subprocess
import tempfile
import shutil

class PythonSandbox:
    def __init__(self, sandbox_path):
        self.sandbox_path = os.path.abspath(sandbox_path)
        self.create_sandbox()

    def create_sandbox(self):
        if not os.path.exists(self.sandbox_path):
            os.makedirs(self.sandbox_path)
        
        # Create a virtual environment in the sandbox
        subprocess.run([sys.executable, "-m", "venv", self.sandbox_path], check=True)
        
        # Set up activation command
        if sys.platform == "win32":
            self.python_path = os.path.join(self.sandbox_path, "Scripts", "python.exe")
            self.pip_path = os.path.join(self.sandbox_path, "Scripts", "pip.exe")
        else:
            self.python_path = os.path.join(self.sandbox_path, "bin", "python")
            self.pip_path = os.path.join(self.sandbox_path, "bin", "pip")

    def install_packages(self, package_names):
        package_install_status = {}
        for package in package_names:
            try:
                result = subprocess.run([self.pip_path, "install", package], 
                                        capture_output=True, text=True, check=True)
                package_install_status[package] = {
                    "success": True,
                    "message": f"Successfully installed {package}",
                    "details": result.stdout
                }
            except subprocess.CalledProcessError as e:
                package_install_status[package] = {
                    "success": False,
                    "message": f"Failed to install {package}",
                    "details": e.stderr
                }
        return package_install_status

    def execute_code(self, code):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as temp_file:
            temp_file.write(code)
            temp_file_path = temp_file.name

        try:
            # Execute the code and capture output
            result = subprocess.run([self.python_path, temp_file_path], 
                                    capture_output=True, text=True)

            return {
                "stdout": result.stdout,
                "stderr": result.stderr,
                "returncode": result.returncode
            }
        finally:
            os.unlink(temp_file_path)

    def cleanup(self):
        shutil.rmtree(self.sandbox_path)

# Example usage
if __name__ == "__main__":
    sandbox = PythonSandbox("./my_sandbox")
    
    # Install a library
    print(sandbox.install_packages(["requests", "pandas", "matplotlib"]))

    # Use the installed library
    result = sandbox.execute_code("""
import pandas as pd
import matplotlib.pyplot as plt

# Data
data = {
    'Erin': [23.68, 18.04, 23.86, 0.00, 11.18, 18.33, 30.14, 29.78, 11.40, 23.76, 18.53, 5.39, 9.42, 21.24, 54.50, 25.17, 107.06, 16.28, 13.64, 5.14, 75.31],
    'Sophie': [27.86, 12.32, 19.46, 6.93, 16.35, 20.96, 35.20, 26.50, 10.70, 23.76, 18.53, 5.39, 9.42, 21.24, 54.50, 25.17, 107.06, 16.28, 13.64, 5.14, 75.31],
    'Sulav': [46.40, 47.18, 52.67, 8.80, 15.58, 16.25, 41.80, 28.80, 12.50, 23.76, 18.53, 5.39, 9.42, 21.24, 54.50, 25.17, 107.06, 16.28, 13.64, 5.14, 75.31],
    'Nicole': [26.71, 36.43, 33.76, 11.72, 17.45, 28.37, 32.67, 35.37, 15.45, 23.76, 18.53, 5.39, 9.42, 21.24, 54.50, 25.17, 107.06, 16.28, 13.64, 5.14, 75.31],
    'Volody': [46.40, 50.14, 44.76, 27.78, 17.45, 30.78, 37.40, 29.78, 15.35, 23.76, 18.53, 5.39, 9.42, 21.24, 54.50, 25.17, 107.06, 16.28, 13.64, 5.14, 75.31],
    'Total': [171.05, 164.12, 174.52, 55.22, 78.00, 114.69, 177.22, 150.23, 65.40, 118.80, 92.67, 26.95, 47.09, 106.20, 272.50, 125.85, 535.30, 81.39, 68.21, 25.72, 376.53]
}

# Categories
categories = [
    'Port Vell', 'Mercader', 'Cachitos', 'Croq & Roll', 'El Petit Mos', 'Cerueseria Catalana', 'Obe', 'Samoa', 'Brunch and Cake', 'Resturant Forever', 'Forty Fives', 'Bar Cafeteria Es Tast', 'Balmes', 'Kubik', 'VL 30', 'Sagrada Familia', 'Kayaking', 'Park Guell', 'Opium', 'Supermercado', 'Freenow'
]

# Create DataFrame
df = pd.DataFrame(data, index=categories)

# Plotting
df.plot(kind='bar', figsize=(14, 7), colormap='viridis')
plt.title('Expenses by Category and Person')
plt.xlabel('Categories')
plt.ylabel('Amount ($)')
plt.xticks(rotation=45)
plt.legend(title='Persons')
plt.grid(axis='y')
plt.tight_layout()
plt.show()
""")
    print("Output:", result['stdout'])
    print("Errors:", result['stderr'])
    print("Return code:", result['returncode'])

    # Clean up the sandbox when done
    sandbox.cleanup()