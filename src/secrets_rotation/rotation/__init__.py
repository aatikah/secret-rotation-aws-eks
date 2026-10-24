"""Rotation logic for databases, API credentials, and certificates.

Each module implements the AWS Secrets Manager rotation contract where it
applies — the four steps ``createSecret``, ``setSecret``, ``testSecret``,
``finishSecret`` — plus local demonstrations that run without AWS.
"""
