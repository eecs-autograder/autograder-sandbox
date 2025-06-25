from autograder_sandbox import AutograderSandbox

with AutograderSandbox() as sandbox:
    result = sandbox.run_command(['echo', 'Hello World!'], check=True, timeout=10)
    print(result.stdout.read().decode())
