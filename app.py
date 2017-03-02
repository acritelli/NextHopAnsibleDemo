from flask import Flask, request, render_template
from botocore.exceptions import ClientError
from threading import Thread
import sys, sqlite3, boto3, time, logging, string, random, subprocess

sys.tracebacklimit=0

app = Flask(__name__)

@app.route('/', methods=['GET', 'POST'])
def index():
    return render_template("create_lab.html")

@app.route('/build', methods=['POST'])
def build():
    #Get the demo number from our sqlite database and die if 0 demos are left
    #The sqlite DB only has one entry, which is the number of demos
    conn = sqlite3.connect('labDatabase.db')
    cur = conn.cursor()
    cur.execute('SELECT * from labConfig')
    result = cur.fetchone()
    numAvailDemos = result[1]
    if numAvailDemos == 0:
        conn.close()
        return render_template("noDemos.html")
    else:
        studentNumber = numAvailDemos
        numAvailDemos -= 1
        cur.execute('UPDATE labConfig SET value=? WHERE param=?', (numAvailDemos, "availableDemos"))
        conn.commit()
        conn.close()
        thread = Thread(target = deploy_demo, kwargs={'destEmail': request.form['email'], 'studentName': request.form['name'], 'studentNumber': studentNumber})
        thread.start()
        return render_template("confirmationPage.html", name=request.form['name'], email=request.form['email'], studentNumber=studentNumber)

def deploy_demo(destEmail, studentName, studentNumber):

    ##### VARS #####

    #TODO: add these to sqlite DB
    #Core information
    coreVPCID = 
    corePublicRouteTableID = CHANGEME
    coreIP = CHANGEME
    coreSubnet = "10.0.0.0/16"
    amiImageID = CHANGEME
    sourceEmail = "demo@acritelli.com"


    logger = logging.getLogger(__name__)
    logger.setLevel(logging.DEBUG)
    consoleHandler = logging.StreamHandler()
    logger.addHandler(consoleHandler)
    fileHandler = logging.FileHandler("deploymentLog.txt")
    logger.addHandler(fileHandler)

    logger.debug("[Student: %s] - Starting demo deployment. Student: %s Email: %s Demo Number: %s" % (studentNumber, studentName, destEmail, studentNumber))

    #Create subnets based on the demo number
    #10.<num>.0.0/16
    vpcSubnet = "10." + str(studentNumber) + ".0.0/16"
    public_subnet = "10." + str(studentNumber) + ".1.0/24"
    private_subnet = "10." + str(studentNumber) + ".2.0/24"
    username = "student" + str(studentNumber)
    ##### END VARS #####

    #Used for adding tags
    resourceList = []
    try:
        client = boto3.client('ec2',
            region_name="us-east-1"
        )

        #Build a VPC
        response = client.create_vpc(CidrBlock=vpcSubnet)
        studentVPCID = response['Vpc']['VpcId']
        resourceList.append(studentVPCID)
        logger.debug("[Student: %s] - Created VPC %s with IP space %s", studentNumber, studentVPCID, vpcSubnet)

        #Get the default route table
        response = client.describe_route_tables(
            Filters=[
                {
                    'Name': 'vpc-id',
                    'Values': [
                        studentVPCID,
                    ]
                },
            ]
        )
        mainRouteTableID = ""
        for table in response['RouteTables']:
            if table['Associations'][0]['Main'] == True:
                mainRouteTableID=table['RouteTableId']
        resourceList.append(mainRouteTableID)
        logger.debug("[Student: %s] - Got main route table %s", studentNumber, mainRouteTableID)


        #Create an IG and attach to our new VPC
        response = client.create_internet_gateway()
        igID = response['InternetGateway']['InternetGatewayId']
        resourceList.append(igID)
        response = client.attach_internet_gateway(InternetGatewayId=igID, VpcId=studentVPCID)
        logger.debug("[Student: %s] - Created Internet Gateway %s", studentNumber, igID)

        #Create an EIP
        response = client.allocate_address(Domain=studentVPCID)
        eipID = response['AllocationId']
        logger.debug("[Student: %s] - Got EIP %s", studentNumber, eipID)

        #Create public and private subnets
        response = client.create_subnet(VpcId=studentVPCID, CidrBlock=public_subnet)
        publicSubnetID = response['Subnet']['SubnetId']
        resourceList.append(publicSubnetID)
        logger.debug("[Student: %s] - Created public subnet %s with IP space %s", studentNumber, publicSubnetID, public_subnet)

        response = client.modify_subnet_attribute(
            SubnetId=publicSubnetID,
            MapPublicIpOnLaunch={'Value': True}
        )
        logger.debug("[Student: %s] - Configured %s for auto public IP allocation", studentNumber, publicSubnetID)

        response = client.create_subnet(VpcId=studentVPCID, CidrBlock=private_subnet)
        privateSubnetID = response['Subnet']['SubnetId']
        resourceList.append(privateSubnetID)
        logger.debug("[Student: %s] - Created private subnet %s with IP space %s", studentNumber, privateSubnetID, private_subnet)

        #Create route tables and add route out of IG
        response = client.create_route_table(VpcId=studentVPCID)
        publicRouteTableID = response['RouteTable']['RouteTableId']
        resourceList.append(publicRouteTableID)
        response = client.create_route(
            RouteTableId=publicRouteTableID,
            DestinationCidrBlock="0.0.0.0/0",
            GatewayId=igID,
        )
        logger.debug("[Student: %s] - Created upblic route table %s", studentNumber, publicRouteTableID)

        #Create a NAT gateway
        response = client.create_nat_gateway(
            SubnetId=publicSubnetID,
            AllocationId=eipID)
        NATgwID = response['NatGateway']['NatGatewayId']
        logger.debug("[Student: %s] - Began provisioning NAT gateway %s", studentNumber, NATgwID)

        #Create a security group that permits all traffic
        response = client.create_security_group(
            GroupName='NextHopTraffic',
            Description='All traffic',
            VpcId=studentVPCID
        )
        SecurityGroupID = response['GroupId']
        resourceList.append(SecurityGroupID)
        response = client.authorize_security_group_ingress(
            GroupId=SecurityGroupID,
            IpProtocol='-1',
            FromPort=-1,
            ToPort=-1,
            CidrIp='0.0.0.0/0'
        )
        logger.debug("[Student: %s] - Created permit all security group %s", studentNumber, SecurityGroupID)

        #Create peering connections
        response = client.create_vpc_peering_connection(
            VpcId=coreVPCID,
            PeerVpcId=studentVPCID
        )
        vpcPeeringID = response['VpcPeeringConnection']['VpcPeeringConnectionId']
        resourceList.append(vpcPeeringID)
        response = client.accept_vpc_peering_connection(
            VpcPeeringConnectionId=vpcPeeringID
        )
        logger.debug("[Student: %s] - Created VPC peering connection %s", studentNumber, vpcPeeringID)

        #Add routes for the peering
        response = client.create_route(
            RouteTableId=corePublicRouteTableID,
            DestinationCidrBlock=vpcSubnet,
            VpcPeeringConnectionId=vpcPeeringID
        )

        response = client.create_route(
            RouteTableId=mainRouteTableID,
            DestinationCidrBlock=coreSubnet,
            VpcPeeringConnectionId=vpcPeeringID
        )

        response = client.create_route(
            RouteTableId=publicRouteTableID,
            DestinationCidrBlock=coreSubnet,
            VpcPeeringConnectionId=vpcPeeringID
        )
        logger.debug("[Student: %s] - Added routes for peering connections", studentNumber)

        #Associate the public subnet to the public routing table
        response = client.associate_route_table(
            SubnetId=publicSubnetID,
            RouteTableId=publicRouteTableID
        )
        logger.debug("[Student: %s] - Associated public subnet with public routing table", studentNumber)

        #Create EC2 VMs
        #This is ABSOLUTELY NOT cryptographically secure
        characters = string.ascii_letters + string.digits
        studentPassword = "".join(random.choice(characters) for x in range(random.randint(16,16)))
        commandString = "#!/bin/bash\necho " + studentPassword + " | passwd ansible --stdin\n"

        #Deploy VM into public subnet
        response = client.run_instances(
            ImageId=amiImageID,
            MinCount=1,
            MaxCount=1,
            SecurityGroupIds=[SecurityGroupID],
            UserData=commandString,
            SubnetId=publicSubnetID,
            InstanceType="t2.micro"
        )

        publicInstanceID = response['Instances'][0]['InstanceId']
        resourceList.append(publicInstanceID)
        publicInstancePrivateIP = response['Instances'][0]['PrivateIpAddress']
        logger.debug("[Student: %s] - Created public EC2 instance %s", studentNumber, publicInstanceID)

        #Deploy VM into private subnet
        response = client.run_instances(
            ImageId=amiImageID,
            MinCount=1,
            MaxCount=1,
            SecurityGroupIds=[SecurityGroupID],
            UserData=commandString,
            SubnetId=privateSubnetID,
            InstanceType="t2.micro"
        )
        privateInstanceID = response['Instances'][0]['InstanceId']
        resourceList.append(privateInstanceID)
        privateInstancePrivateIP = response['Instances'][0]['PrivateIpAddress']
        logger.debug("[Student: %s] - Created private EC2 instance %s", studentNumber, privateInstanceID)

        #Add route of NAT gateway to main route table
        #We need to wait until NAT gateway is provisioned. They take awhile.
        isGatewayReady = False
        while not isGatewayReady:
            response = client.describe_nat_gateways(NatGatewayIds=[NATgwID])
            if response['NatGateways'][0]['State'] == 'available':
                isGatewayReady = True
                logger.debug("[Student: %s] - NAT gateway creation completed %s", studentNumber, NATgwID)
            else:
                logger.debug("[Student: %s] - Still pending NAT gateway creation %s", studentNumber, NATgwID)
                time.sleep(30)

        response = client.create_route(
            RouteTableId=mainRouteTableID,
            DestinationCidrBlock="0.0.0.0/0",
            NatGatewayId=NATgwID
        )
        logger.debug("[Student: %s] - Added route to public route table for NAT gateway", studentNumber)

        #Wait until EC2 instance is ready and get public IP
        isInstanceReady = False
        while not isInstanceReady:
            response = client.describe_instances(InstanceIds=[publicInstanceID])
            if response['Reservations'][0]['Instances'][0]['State']['Name'] == 'running':
                publicInstancePublicIP =  response['Reservations'][0]['Instances'][0]['PublicIpAddress']
                isInstanceReady = True
                logger.debug("[Student: %s] - Public EC2 instance creation completed %s", studentNumber, publicInstanceID)
            else:
                logger.debug("[Student: %s] - Still pending EC2 creation %s", studentNumber, publicInstanceID)
                time.sleep(30)

        #Add user to local box os that they can SSH in
        subprocess.call("ansible-playbook addUser.yml --extra-vars \"" + "username=" + username + " password=" + studentPassword + "\"", shell=True)
        logger.debug("[Student: %s] - Adding user to local server", studentNumber)

        #Email the username, password, etc to the user
        emailSubject = "NextHop Ansible Demo Information"

        #Construct email body
        emailBody = "Thanks for signing up for the NextHop Ansible Demo. Your info is below\n\n"
        emailBody += "Username: " + username + "\n"
        emailBody += "Password: " + studentPassword + "\n\n"
        emailBody += "Webserver Public IP: " + publicInstancePublicIP + "\n"
        emailBody += "Webserver Private IP: " + publicInstancePrivateIP + "\n"
        emailBody += "Database Server Private IP: " + privateInstancePrivateIP + "\n\n"
        emailBody += "You can use your credentials to log into the core server at " + coreIP + "\n"
	emailBody += "Download the demo guide at https://acritelli.com/presentations/nexthopAnsible2017/ansible_demo_guide.docx"

        emailClient = boto3.client('ses',
                region_name="us-east-1"
        )

        response = emailClient.send_email(
            Source=sourceEmail,
            Destination={'ToAddresses': [destEmail]},
            Message={
                'Subject': {'Data': emailSubject},
                'Body': {
                    'Text': {
                        'Data': emailBody
                    }
                }
            }
        )
        logger.debug("[Student: %s] - Sent email to %s at %s", studentNumber, studentName, destEmail)

        response = client.create_tags(
            Resources=resourceList,
            Tags=[{'Key': 'Lab', 'Value': 'NextHop'}]
        )
        logger.debug("[Student: %s] - Added tags for all resources", studentNumber)
        return
    #Probably should do a better job of catching more specific exceptions
    except Exception as e:
        logger.critical("[Student: %s] - Deployment failed. Error: %s", studentNumber, e, exc_info=True)
        return

if __name__ == "__main__":
    app.run(debug=True, host='0.0.0.0', port=80)
