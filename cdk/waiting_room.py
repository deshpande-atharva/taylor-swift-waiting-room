"""
YOUR WAITING ROOM  -  Option C: Redis / ElastiCache
====================================================
A time-based admission counter stored in Redis (ElastiCache cache.t4g.micro).

DESIGN
  - JoinQueue: INCR a Redis counter to assign each visitor a sequential position.
    Also SETNX a start-time key so we know when the line opened.
  - CheckStatus: compute max_admitted = (now - start_time) * rate.
    If the visitor's position <= max_admitted AND they haven't been admitted yet,
    write the admission record to DynamoDB and return the token.
  - No AdvanceServingCounter Lambda needed: admission is computed from elapsed
    time, not a counter that must be incremented on a schedule.

NETWORKING
  - VPC with PRIVATE_ISOLATED subnets only (no NAT Gateway -- $0 extra).
  - DynamoDB Gateway VPC Endpoint (free) so CheckStatus can write admissions.
  - Lambda functions are placed in the VPC so they can reach Redis.
  - OrderProducer stays OUTSIDE the VPC (unchanged) -- it reads admissions
    via the gate, which uses DynamoDB (a public service).
"""
from pathlib import Path

import aws_cdk as cdk
from aws_cdk import aws_apigateway as apigw
from aws_cdk import aws_cloudwatch as cw
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_elasticache as elasticache
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_logs as logs
from constructs import Construct

HANDLERS = Path(__file__).resolve().parent.parent / "lambdas" / "waiting_room"


class WaitingRoom(Construct):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        api: apigw.RestApi,
        admissions_per_second: float = 10,
    ) -> None:
        super().__init__(scope, construct_id)
        self.admissions_per_second = admissions_per_second

        # -- 1. REQUIRED: the table the provided gate reads -----------------
        self.admissions_table = dynamodb.Table(
            self, "Admissions",
            table_name="week5-wr-admissions",
            partition_key=dynamodb.Attribute(name="visitor_id", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            time_to_live_attribute="ttl",
            removal_policy=cdk.RemovalPolicy.DESTROY,
        )

        # -- 2. VPC (no NAT, private-isolated only) -------------------------
        self.vpc = ec2.Vpc(
            self, "Vpc",
            max_azs=2,
            nat_gateways=0,
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    name="Isolated",
                    subnet_type=ec2.SubnetType.PRIVATE_ISOLATED,
                    cidr_mask=24,
                ),
            ],
        )

        # Free DynamoDB Gateway Endpoint -- lets VPC Lambdas write admissions
        self.vpc.add_gateway_endpoint(
            "DynamoEndpoint",
            service=ec2.GatewayVpcEndpointAwsService.DYNAMODB,
        )

        # -- 3. Security group (Redis port 6379) ----------------------------
        self.redis_sg = ec2.SecurityGroup(
            self, "RedisSG",
            vpc=self.vpc,
            description="Lambda to Redis on port 6379",
        )
        self.redis_sg.add_ingress_rule(
            self.redis_sg, ec2.Port.tcp(6379), "Allow Redis from same SG",
        )

        # -- 4. ElastiCache: ONE cache.t4g.micro node ----------------------
        subnet_group = elasticache.CfnSubnetGroup(
            self, "RedisSubnets",
            description="WR Redis subnets",
            subnet_ids=[s.subnet_id for s in self.vpc.isolated_subnets],
        )

        self.redis_cluster = elasticache.CfnCacheCluster(
            self, "Redis",
            cluster_name="week5-wr-redis",
            cache_node_type="cache.t4g.micro",
            engine="redis",
            num_cache_nodes=1,
            vpc_security_group_ids=[self.redis_sg.security_group_id],
            cache_subnet_group_name=subnet_group.ref,
        )

        # -- 5. Lambda functions (inside VPC) --------------------------------
        env = {
            "ADMISSIONS_TABLE": self.admissions_table.table_name,
            "ADMIT_PER_SECOND": str(int(admissions_per_second)),
            "POLL_INTERVAL_SECONDS": "5",
            "ADMISSION_VALID_SECONDS": "600",
            "REDIS_HOST": self.redis_cluster.attr_redis_endpoint_address,
            "REDIS_PORT": self.redis_cluster.attr_redis_endpoint_port,
        }
        code = lambda_.Code.from_asset(str(HANDLERS))

        vpc_subnets = ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_ISOLATED)

        def make_fn(cid, function_name, handler):
            return lambda_.Function(
                self, cid,
                function_name=function_name,
                runtime=lambda_.Runtime.PYTHON_3_12,
                handler=handler,
                code=code,
                timeout=cdk.Duration.seconds(10),
                memory_size=128,
                environment=env,
                log_retention=logs.RetentionDays.ONE_WEEK,
                vpc=self.vpc,
                vpc_subnets=vpc_subnets,
                security_groups=[self.redis_sg],
            )

        self.join_fn = make_fn("Join", "week5-wr-join", "join_handler.lambda_handler")
        self.status_fn = make_fn("Status", "week5-wr-status", "status_handler.lambda_handler")

        # Permissions: join needs Redis only (network), status needs Redis + DynamoDB
        self.admissions_table.grant_read_write_data(self.status_fn)
        # join also needs DynamoDB if we want it to check anything, but for Option C
        # join only writes to Redis.  Grant read to join so it could verify duplicates
        # if needed in the future, but the core path doesn't require it.

        self.functions = [self.join_fn, self.status_fn]

        # -- 6. REQUIRED: the two routes ------------------------------------
        waiting_room = api.root.add_resource("waiting-room")
        waiting_room.add_resource("join").add_method("POST", apigw.LambdaIntegration(self.join_fn))
        waiting_room.add_resource("status").add_resource("{visitor_id}").add_method(
            "GET", apigw.LambdaIntegration(self.status_fn))

    def dashboard_widgets(self) -> list:
        """Three widgets showing Redis and admission-table health."""
        one_min = cdk.Duration.minutes(1)
        cluster_id = self.redis_cluster.cluster_name or "week5-wr-redis"

        return [
            cw.GraphWidget(
                title="Redis - connections & commands/s",
                left=[
                    cw.Metric(namespace="AWS/ElastiCache", metric_name="CurrConnections",
                              dimensions_map={"CacheClusterId": cluster_id, "CacheNodeId": "0001"},
                              period=one_min, statistic="Maximum", label="connections"),
                ],
                right=[
                    cw.Metric(namespace="AWS/ElastiCache", metric_name="SetTypeCmds",
                              dimensions_map={"CacheClusterId": cluster_id, "CacheNodeId": "0001"},
                              period=one_min, statistic="Sum", label="set-type cmds"),
                    cw.Metric(namespace="AWS/ElastiCache", metric_name="GetTypeCmds",
                              dimensions_map={"CacheClusterId": cluster_id, "CacheNodeId": "0001"},
                              period=one_min, statistic="Sum", label="get-type cmds"),
                ],
                width=8,
            ),
            cw.GraphWidget(
                title="Redis - CPU utilization",
                left=[
                    cw.Metric(namespace="AWS/ElastiCache", metric_name="EngineCPUUtilization",
                              dimensions_map={"CacheClusterId": cluster_id, "CacheNodeId": "0001"},
                              period=one_min, statistic="Maximum", label="engine CPU %"),
                    cw.Metric(namespace="AWS/ElastiCache", metric_name="CPUUtilization",
                              dimensions_map={"CacheClusterId": cluster_id, "CacheNodeId": "0001"},
                              period=one_min, statistic="Maximum", label="host CPU %"),
                ],
                width=8,
            ),
            cw.GraphWidget(
                title="Admissions table - writes",
                left=[
                    self.admissions_table.metric(
                        "ConsumedWriteCapacityUnits", period=one_min, statistic="Sum", label="WCU consumed"),
                ],
                width=8,
            ),
        ]
