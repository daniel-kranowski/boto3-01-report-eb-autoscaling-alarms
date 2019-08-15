# Boto 3 for AWS Elastic Beanstalk and Cloudwatch

This python module uses the [Boto 3](https://boto3.readthedocs.io/en/latest/) AWS client library
to retrieve AWS Cloudwatch alarm history related to ASG autoscaling activities for an Elastic
Beanstalk environment, and writes them out to CSV files.

The AWS commands performed by this module are read-only.  They will not change the state
of your AWS resources.

The module writes AWS responses into a local cache directory, so that you can request raw AWS info
once and then analyze it repeatedly.

Technologies:

* Python 3
* Boto 3
* AWS Cloudwatch, AutoScaling, Elastic Beanstalk

If you wish to run this code, you will need an AWS account and an Elastic Beanstalk environment
(or there will be nothing to do).

## Setup

I use [pyenv](https://github.com/pyenv/pyenv) and [virtualenv](https://virtualenv.pypa.io/en/stable/)
to make a sandboxed python environment.  You can skip these two lines, but here's what I do:
```
virtualenv -p ~/.pyenv/versions/3.4.3/bin/python3.4 py-virtualenv
source py-virtualenv/bin/activate
```

Now type this in the root project dir, to install required dependencies:
```
pip install -r requirements.txt
```

You'll also need an AWS profile in `~/.aws/credentials`.
You can create the credentials file in a text editor, or run
[aws configure](http://docs.aws.amazon.com/cli/latest/userguide/cli-config-files.html).

## Run

For general command-line help:
```
python -m report_eb_autoscaling_alarms --help
```

To run the module with default AWS settings, relying on normal cache behavior, and writing out all
three CSV files:
```
python -m report_eb_autoscaling_alarms --write-csv all
```

As an example of using more command-line options, this specifies an alternate AWS profile and region,
as well as instructing the module to refresh its cache of certain object types, and also write only
two of the output CSV files:
```
python -m report_eb_autoscaling_alarms \
  --recache alarm_history scaling \
  --write-csv cw_alarm_history asg_activities \
  --aws-profile default \
  --aws-region us-west-2
```

The recache option is necessary only when you think an existing cached object is out of date.
When the cache is empty, this module fills it regardless of the recache option.  Or you can simply
delete the cache dir and all objects will be refreshed next time.

## Cache and outputs

Cache files are written to a `./cache` dir.  CSV files are written to an `./output` dir.

Here are the cache files this module produces:

* describe_alarm_history-<alarm-name>.json
* describe_alarms.json
* describe_auto_scaling_groups-<asg-name>.json
* describe_environment_resources-<beanstalk-env>.json
* describe_environments.json
* describe_scaling_activities-<asg-name>.json

And the CSV output files:

* asg_activities.csv
* cw_alarm_history.csv
* cw_alarms.csv

I found it useful to open the result CSV files in Excel and manipulate them more there.

### When we choose to refresh cache object types

We only make an AWS network request when the cache is empty or you have specified on the command-line
that we should refresh the cache for a certain object type.  You can force a recache of everything
simply by deleting the cache dir and running this module again.

Calculations of the three CSV outputs (alarms, alarm_history, scaling_activity) share the need for
these object types: envs, resources, and alarms.  If you want to refresh the cache, and you are writing
all CSVs in one go, it would be redundant and slow to refresh those object types each time they are
requested, so we refresh them just once at the beginning.

The alarm_history CSV uniquely needs alarm_history cache objects.  The scaling_activity CSV uniquely
needs objects of type auto_scaling_groups and scaling_activities.

### Limitations

Multi-dimensional alarms are ignored.
