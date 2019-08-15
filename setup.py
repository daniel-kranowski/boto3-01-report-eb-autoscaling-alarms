from setuptools import setup, find_packages

setup(
    name='report_eb_autoscaling_alarms',
    version='0.1.0',
    description='Retrieves Cloudwatch alarm history and ASG scaling activities for an Elastic Beanstalk environment',
    author='Daniel Kranowski',
    license='MIT',
    packages=find_packages()
)
