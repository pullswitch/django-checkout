from setuptools import setup, find_packages


setup(
    name = "django-checkout",
    version = "0.2.0",
    author = "Dave Lowe",
    author_email = "dave@hellopullswitch.com",
    description = "a Django app for handling subscriptions, orders and transactions",
    long_description = open("README.mkd").read(),
    license = "MIT",
    url = "http://github.com/pullswitch/django-checkout",
    packages = find_packages(),
    install_requires = [
        "django-form-utils==0.2.0",
    ],
    classifiers = [
        "Development Status :: 4 - Beta",
        "Environment :: Web Environment",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python",
        "Framework :: Django",
    ]
)



PACKAGE = "checkout"
NAME = "django-checkout"
DESCRIPTION = "a pluggable app for handling orders and transactions"
AUTHOR = "Pullswitch"
AUTHOR_EMAIL = "dave@hellopullswitch.com"
URL = "http://github.com/pullswitch/django-checkout"
VERSION = __import__(PACKAGE).__version__


setup(
    name=NAME,
    version=VERSION,
    description=DESCRIPTION,
    long_description=read("README.mkd"),
    author=AUTHOR,
    author_email=AUTHOR_EMAIL,
    license="BSD",
    url=URL,
    packages=find_packages(exclude=["tests.*", "tests"]),
    package_data=find_package_data(PACKAGE, only_in_packages=False),
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Environment :: Web Environment",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: BSD License",
        "Operating System :: OS Independent",
        "Programming Language :: Python",
        "Framework :: Django",
    ],
    zip_safe=False
)
