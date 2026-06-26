"""Vapor CLI - AWS Cost Audit Tool."""

from setuptools import setup, find_packages

setup(
    name="vapor-cli",
    version="0.1.0",
    description="AWS cost audit CLI powered by LangGraph and GPT-5-mini",
    packages=find_packages(),
    py_modules=["vapor"],
    python_requires=">=3.11",
    install_requires=[
        "boto3>=1.34.0",
        "langgraph>=0.2.0",
        "openai>=1.30.0",
        "rich>=13.7.0",
        "python-dotenv>=1.0.0",
    ],
    entry_points={
        "console_scripts": [
            "vapor=vapor.cli:main",
        ],
    },
)
