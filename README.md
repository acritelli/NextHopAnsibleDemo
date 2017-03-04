Code from my live Ansible demo at RIT NextHop. README is a work in progress and will be updated soon.

# Overivew

This code builds the demo environment from my Ansible presentation at RIT's NextHop. It's a Flask application with an extremely poor web interface that allows a demo participant to put in their username and password and have a demo environment provisioned for them. It got the job done for this presentation.

This is very much a quick and dirty, one-off script. I wouldn't recommend re-using it in its entirety, but I'm publishing for anyone who is interested.

The following is provisioned for each student:
* Demo VPC peered to a central VPC
* Private subnet with a NAT Gateway
* Public subnet with an Internet Gateway
* Two EC2 instances with an "ansible" user and the randomly generated password: one in the private subnet and one in the public subnet
* An email is sent to the student via SES with their username (i.e. "student1") and generated password from demo@acritelli.com
* Everything is tagged as NextHop

# Prerequisites

The topology built for each student relies on a central VPC containing a jumphost that this script is run on. A user with a random password is added via Ansible on the jumphost. Additionally, two instances are deployed for the student: on in their public subnet and one in their private subnet. To accomplish these goals, it relies on a few things:

* Dependencies: Flask and Boto3
* Ansible installed on the control machine, and the ability for the user running the app to perform passwordless sudo (to add users)
* A central VPC that all demo VPCs can be peered to
* An AMI for deploying the two demo EC2 instances

# Configuration

* Modify the NUM_AVAIL_DEMOS in the buildDB.py script and execute. This builds a small SQLite database with the number of demos available, allowing for thread safety when running the web application
* Modify the app.py and set the coreVPCID, corePublicRouteTableID, coreIP, and amiImageID
* Run app.py - By default it launches flask on port 80, but ideally you would proxy this with something like nginx

# Known issues
* Sometimes there are issues with adding a VPC peering relationship. It seems like some kind of race condition where boto3 will return a VPC ID for the demo subnet, but the VPC hasn't actually been created yet and the peering attempt fails.
