from setuptools import setup, find_packages

setup(
    name="atulya_brain",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[
        "numpy>=1.21.0",
        "opencv-python>=4.5.0",
        "torch>=1.10.0",
        "scipy>=1.7.0",
    ],
    extras_require={
        'full': ['tensorflow>=2.8.0']
    },
    python_requires=">=3.8",
)