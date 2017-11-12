from setuptools import setup, find_packages

install_requires = []

setup(
    name="pg_obfuscator",
    version="0.1",
    description="Obfuscate a pg_dump file",
    author="bwallad",
    author_email="bwallad@gmail.com",
    install_requires=install_requires,
    scripts=[
        "bin/pg_obfuscate",
    ],
    packages=find_packages()
)
