import setuptools
from checkout2 import name, version

with open("README.md", "r") as fh:
    long_description = fh.read()

setuptools.setup(
    name=name,
    version=version,
    author="Antti-Juhani Kaijanaho",
    author_email="antti-juhani@kaijanaho.fi",
    description="Wrapper for the Checkout Finland Payment Service API",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/ajkaijanaho/checkout-psp-client",
    packages=setuptools.find_packages(),
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Environment :: Web Environment",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.7",
        "Topic :: Office/Business"
    ],
    install_requires=['requests'],
    python_requires='>=3',
)
