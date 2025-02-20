import argparse
import glob
import os
import shutil
import site
import subprocess
import sys

script_dir = os.getcwd()

# Use this to set your command-line flags. For the full list, see:
# https://github.com/oobabooga/text-generation-webui/#starting-the-web-ui
CMD_FLAGS = '--chat --model-menu'


def run_cmd(cmd, assert_success=False, environment=True, capture_output=False, env=None):
    # Use the conda environment
    if environment:
        conda_env_path = os.path.join(script_dir, "installer_files", "env")
        if sys.platform.startswith("win"):
            conda_bat_path = os.path.join(script_dir, "installer_files", "conda", "condabin", "conda.bat")
            cmd = "\"" + conda_bat_path + "\" activate \"" + conda_env_path + "\" >nul && " + cmd
        else:
            conda_sh_path = os.path.join(script_dir, "installer_files", "conda", "etc", "profile.d", "conda.sh")
            cmd = ". \"" + conda_sh_path + "\" && conda activate \"" + conda_env_path + "\" && " + cmd
    
    # Run shell commands
    result = subprocess.run(cmd, shell=True, capture_output=capture_output, env=env)
    
    # Assert the command ran successfully
    if assert_success and result.returncode != 0:
        print("Command '" + cmd + "' failed with exit status code '" + str(result.returncode) + "'. Exiting...")
        sys.exit()
    return result


def check_env(environment=True):
    # If we have access to conda, we are probably in an environment
    conda_exist = run_cmd("conda", environment=environment, capture_output=True).returncode == 0
    if not conda_exist:
        print("Conda is not installed. Exiting...")
        sys.exit()
    
    # Ensure this is a new environment and not the base environment
    if os.environ["CONDA_DEFAULT_ENV"] == "base":
        print("Create an environment for this project and activate it. Exiting...")
        sys.exit()


def install_dependencies(environment=True):
    # Select your GPU or, choose to run in CPU mode
    print("What is your GPU")
    print()
    print("A) NVIDIA")
    print("B) AMD")
    print("C) Apple M Series")
    print("D) None (I want to run in CPU mode)")
    print()
    gpuchoice = input("Input> ").lower()

    if gpuchoice == "d":
        print("\nOnce the installation ends, make sure to open webui.py with a text editor and add the --cpu flag to CMD_FLAGS.\n")

    # Install the version of PyTorch needed
    if gpuchoice == "a":
        run_cmd("conda install -y -k pytorch[version=2,build=py3.10_cuda11.7*] torchvision torchaudio pytorch-cuda=11.7 cuda-toolkit ninja git -c pytorch -c nvidia/label/cuda-11.7.0 -c nvidia", assert_success=True, environment=environment)
    elif gpuchoice == "b":
        print("AMD GPUs are not supported. Exiting...")
        sys.exit()
    elif gpuchoice == "c" or gpuchoice == "d":
        run_cmd("conda install -y -k pytorch torchvision torchaudio cpuonly git -c pytorch", assert_success=True, environment=environment)
    else:
        print("Invalid choice. Exiting...")
        sys.exit()

    # Clone webui to our computer
    run_cmd("git clone https://github.com/oobabooga/text-generation-webui.git", assert_success=True, environment=environment)
    # if sys.platform.startswith("win"):
    #     # Fix a bitsandbytes compatibility issue with Windows
    #     run_cmd("python -m pip install https://github.com/jllllll/bitsandbytes-windows-webui/raw/main/bitsandbytes-0.38.1-py3-none-any.whl", assert_success=True, environment=False)
    
    # Install the webui dependencies
    update_dependencies(environment=environment)


def update_dependencies(environment=True):
    os.chdir("text-generation-webui")
    run_cmd("git pull", assert_success=True, environment=environment)

    # Installs/Updates dependencies from all requirements.txt
    run_cmd("python -m pip install -r requirements.txt --upgrade", assert_success=True, environment=environment)
    extensions = next(os.walk("extensions"))[1]
    for extension in extensions:
        if extension in ['superbooga']:  # No wheels available for dependencies
            continue
            
        extension_req_path = os.path.join("extensions", extension, "requirements.txt")
        if os.path.exists(extension_req_path):
            run_cmd("python -m pip install -r " + extension_req_path + " --upgrade", assert_success=True, environment=environment)

    # The following dependencies are for CUDA, not CPU
    # Check if the package cpuonly exists to determine if torch uses CUDA or not
    cpuonly_exist = run_cmd("conda list cpuonly | grep cpuonly", environment=environment, capture_output=True).returncode == 0
    if cpuonly_exist:
        return

    # Finds the path to your dependencies
    for sitedir in site.getsitepackages():
        if "site-packages" in sitedir:
            site_packages_path = sitedir
            break

    # This path is critical to installing the following dependencies
    if site_packages_path is None:
        print("Could not find the path to your Python packages. Exiting...")
        sys.exit()

    # Fix a bitsandbytes compatibility issue with Linux
    if sys.platform.startswith("linux"):
        shutil.copy(os.path.join(site_packages_path, "bitsandbytes", "libbitsandbytes_cuda117.so"), os.path.join(site_packages_path, "bitsandbytes", "libbitsandbytes_cpu.so"))

    if not os.path.exists("repositories/"):
        os.mkdir("repositories")
    
    # Install GPTQ-for-LLaMa which enables 4bit CUDA quantization
    os.chdir("repositories")
    if not os.path.exists("GPTQ-for-LLaMa/"):
        run_cmd("git clone https://github.com/oobabooga/GPTQ-for-LLaMa.git -b cuda", assert_success=True, environment=environment)
    
    # Install GPTQ-for-LLaMa dependencies
    os.chdir("GPTQ-for-LLaMa")
    run_cmd("git pull", assert_success=True, environment=environment)
    
    # On some Linux distributions, g++ may not exist or be the wrong version to compile GPTQ-for-LLaMa
    if sys.platform.startswith("linux"):
        gxx_output = run_cmd("g++ --version", environment=environment, capture_output=True)
        if gxx_output.returncode != 0 or b"g++ (GCC) 12" in gxx_output.stdout:
            # Install the correct version of g++
            run_cmd("conda install -y -k gxx_linux-64=11.2.0", environment=environment)

    # Compile and install GPTQ-for-LLaMa
    if os.path.exists('setup_cuda.py'):
        os.rename("setup_cuda.py", "setup.py")
        
    run_cmd("python -m pip install .", environment=environment)
    
    # Wheel installation can fail while in the build directory of a package with the same name
    os.chdir("..")
    
    # If the path does not exist, then the install failed
    quant_cuda_path_regex = os.path.join(site_packages_path, "quant_cuda*/")
    if not glob.glob(quant_cuda_path_regex):
        # Attempt installation via alternative, Windows-specific method
        if sys.platform.startswith("win"):
            print("\n\n*******************************************************************")
            print("* WARNING: GPTQ-for-LLaMa compilation failed, but this is FINE and can be ignored!")
            print("* The installer will proceed to install a pre-compiled wheel.")
            print("*******************************************************************\n\n")

            result = run_cmd("python -m pip install https://github.com/jllllll/GPTQ-for-LLaMa-Wheels/raw/main/quant_cuda-0.0.0-cp310-cp310-win_amd64.whl", environment=environment)
            if result.returncode == 0:
                print("Wheel installation success!")
            else:
                print("ERROR: GPTQ wheel installation failed. You will not be able to use GPTQ-based models.")
        else:
            print("ERROR: GPTQ CUDA kernel compilation failed.")
            print("You will not be able to use GPTQ-based models.")
            
        print("Continuing with install..")


def download_model(environment=True):
    os.chdir("text-generation-webui")
    run_cmd("python download-model.py", environment=environment)


def run_model(environment=True):
    os.chdir("text-generation-webui")
    run_cmd(f"python server.py {CMD_FLAGS}", environment=environment)


if __name__ == "__main__":
    # Verifies we are in a conda environment
    need_conda_env=True

    parser = argparse.ArgumentParser()
    parser.add_argument('--update', action='store_true', help='Update the web UI.')
    parser.add_argument('--gotconda', action='store_true', help='Update the web UI.')

    args = parser.parse_args()

    if args.gotconda:
        need_conda_env=False

    check_env(environment=need_conda_env)
    

    if args.update:
        update_dependencies(environment=need_conda_env)
    else:
        # If webui has already been installed, skip and run
        if not os.path.exists("text-generation-webui/"):
            install_dependencies(environment=need_conda_env)
            os.chdir(script_dir)

        # Check if a model has been downloaded yet
        if len(glob.glob("text-generation-webui/models/*/")) == 0:
            download_model(environment=need_conda_env)
            os.chdir(script_dir)

        # Run the model with webui
        run_model(environment=need_conda_env)
