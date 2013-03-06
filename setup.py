from setuptools import setup, find_packages


setup(
    name = "django-checkout",
    version = "0.4.5",
    author = "Dave Lowe",
    author_email = "dave@hellopullswitch.com",
    description = "a Django app for handling subscriptions, orders and transactions",
    long_description = open("README.mkd").read(),
    license = "MIT",
    url = "http://github.com/pullswitch/django-checkout",
    packages = find_packages(),
    install_requires = [
        "django-form-utils==0.2.0",
        "pytz"
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
