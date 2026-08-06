from PyInstaller.utils.hooks import collect_data_files


# The upstream hook collects every model provider installed on the build
# machine. Agent Pet supports the OpenAI-compatible provider in its base
# runtime, so keep the frozen artifact deterministic and bounded to that one.
datas = collect_data_files("langchain")
hiddenimports = ["langchain_openai"]
