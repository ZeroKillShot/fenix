# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from __future__ import print_function

import arrow
import datetime
import json
import os
import taskcluster

from lib.util import convert_camel_case_into_kebab_case

DEFAULT_EXPIRES_IN = '1 year'
_OFFICIAL_REPO_URL = 'https://github.com/mozilla-mobile/fenix'


class TaskBuilder(object):
    def __init__(
        self,
        task_id,
        repo_url,
        git_ref,
        short_head_branch,
        commit,
        owner,
        source,
        scheduler_id,
        date_string,
        tasks_priority='lowest',
        trust_level=1
    ):
        self.task_id = task_id
        self.repo_url = repo_url
        self.git_ref = git_ref
        self.short_head_branch = short_head_branch
        self.commit = commit
        self.owner = owner
        self.source = source
        self.scheduler_id = scheduler_id
        self.tasks_priority = tasks_priority
        self.date = arrow.get(date_string)
        self.trust_level = trust_level

    def craft_assemble_release_task(self, architectures, is_staging=False):
        artifacts = {
            'public/target.{}.apk'.format(arch): {
                "type": 'file',
                "path": '/opt/fenix/app/build/outputs/apk/'
                        '{}Greenfield/release/app-{}-greenfield-release-unsigned.apk'.format(arch, arch),
                "expires": taskcluster.stringDate(taskcluster.fromNow(DEFAULT_EXPIRES_IN)),
            }
            for arch in architectures
        }

        sentry_secret = '{}project/mobile/fenix/sentry'.format(
            'garbage/staging/' if is_staging else ''
        )
        leanplum_secret = '{}project/mobile/fenix/leanplum'.format(
            'garbage/staging/' if is_staging else ''
        )

        pre_gradle_commands = (
            'python automation/taskcluster/helper/get-secret.py -s {} -k {} -f {}'.format(
                secret, key, target_file
            )
            for secret, key, target_file in (
                (sentry_secret, 'dsn', '.sentry_token'),
                (leanplum_secret, 'production', '.leanplum_token'),
            )
        )

        gradle_commands = (
            './gradlew --no-daemon -PcrashReports=true clean test assembleRelease',
        )

        command = ' && '.join(
            cmd
            for commands in (pre_gradle_commands, gradle_commands)
            for cmd in commands
            if cmd
        )

        routes = [] if is_staging else [
            "notify.email.fenix-eng-notifications@mozilla.com.on-failed"
        ]

        return self._craft_build_ish_task(
            name='Build task',
            description='Build Fenix from source code',
            command=command,
            scopes=[
                "secrets:get:{}".format(secret) for secret in (sentry_secret, leanplum_secret)
            ],
            artifacts=artifacts,
            routes=routes,
            treeherder={
                'jobKind': 'build',
                'machine': {
                  'platform': 'android-all',
                },
                'symbol': 'NA',
                'tier': 1,
            },
        )

    def craft_assemble_task(self, variant):
        return self._craft_clean_gradle_task(
            name='assemble: {}'.format(variant),
            description='Building and testing variant {}'.format(variant),
            gradle_task='assemble{}'.format(variant.capitalize()),
            artifacts=_craft_artifacts_from_variant(variant),
            routes=self._craft_branch_routes(variant),
            treeherder={
                'groupSymbol': _craft_treeherder_group_symbol_from_variant(variant),
                'jobKind': 'build',
                'machine': {
                  'platform': _craft_treeherder_platform_from_variant(variant),
                },
                'symbol': 'A',
                'tier': 1,
            },
        )

    def craft_test_task(self, variant):
        return self._craft_clean_gradle_task(
            name='test: {}'.format(variant),
            description='Building and testing variant {}'.format(variant),
            gradle_task='test{}UnitTest'.format(variant.capitalize()),
            treeherder={
                'groupSymbol': _craft_treeherder_group_symbol_from_variant(variant),
                'jobKind': 'test',
                'machine': {
                  'platform': _craft_treeherder_platform_from_variant(variant),
                },
                'symbol': 'T',
                'tier': 1,
            },
        )

    def _craft_branch_routes(self, variant):
        routes = []

        if self.repo_url == _OFFICIAL_REPO_URL and self.short_head_branch == 'master':
            architecture, build_type, product = \
                _get_architecture_and_build_type_and_product_from_variant(variant)
            product = convert_camel_case_into_kebab_case(product)
            postfix = convert_camel_case_into_kebab_case('{}-{}'.format(architecture, build_type))

            routes = [
                'index.project.mobile.fenix.branch.{}.revision.{}.{}.{}'.format(
                    self.short_head_branch, self.commit, product, postfix
                ),
                'index.project.mobile.fenix.branch.{}.latest.{}.{}'.format(
                    self.short_head_branch, product, postfix
                ),
                'index.project.mobile.fenix.branch.{}.pushdate.{}.{}.{}.revision.{}.{}.{}'.format(
                    self.short_head_branch, self.date.year, self.date.month, self.date.day,
                    self.commit, product, postfix
                ),
                'index.project.mobile.fenix.branch.{}.pushdate.{}.{}.{}.latest.{}.{}'.format(
                    self.short_head_branch, self.date.year, self.date.month, self.date.day,
                    product, postfix
                ),
            ]
        return routes

    def craft_detekt_task(self):
        return self._craft_clean_gradle_task(
            name='detekt',
            description='Running detekt over all modules',
            gradle_task='detekt',
            treeherder={
                'jobKind': 'test',
                'machine': {
                  'platform': 'lint',
                },
                'symbol': 'detekt',
                'tier': 1,
            }

        )

    def craft_ktlint_task(self):
        return self._craft_clean_gradle_task(
            name='ktlint',
            description='Running ktlint over all modules',
            gradle_task='ktlint',
            treeherder={
                'jobKind': 'test',
                'machine': {
                  'platform': 'lint',
                },
                'symbol': 'ktlint',
                'tier': 1,
            }
        )

    def craft_lint_task(self):
        return self._craft_clean_gradle_task(
            name='lint',
            description='Running ktlint over all modules',
            gradle_task='lintAarch64GreenfieldRelease',
            treeherder={
                'jobKind': 'test',
                'machine': {
                  'platform': 'lint',
                },
                'symbol': 'lint',
                'tier': 1,
            },
        )

    def _craft_clean_gradle_task(
        self, name, description, gradle_task, artifacts=None, routes=None, treeherder=None
    ):
        return self._craft_build_ish_task(
            name=name,
            description=description,
            command='./gradlew --no-daemon clean {}'.format(gradle_task),
            artifacts=artifacts,
            routes=routes,
            treeherder=treeherder,
        )

    def craft_compare_locales_task(self):
        return self._craft_build_ish_task(
            name='compare-locales',
            description='Validate strings.xml with compare-locales',
            command=(
                'pip install "compare-locales>=5.0.2,<6.0" && '
                'compare-locales --validate l10n.toml .'
            ),
            treeherder={
                'jobKind': 'test',
                'machine': {
                  'platform': 'lint',
                },
                'symbol': 'compare-locale',
                'tier': 2,
            }
        )

    def _craft_build_ish_task(
        self, name, description, command, dependencies=None, artifacts=None, scopes=None,
        routes=None, treeherder=None
    ):
        dependencies = [] if dependencies is None else dependencies
        artifacts = {} if artifacts is None else artifacts
        scopes = [] if scopes is None else scopes
        routes = [] if routes is None else routes

        checkout_command = (
            "export TERM=dumb && "
            "git fetch {} {} --tags && "
            "git config advice.detachedHead false && "
            "git checkout {}".format(
                self.repo_url, self.git_ref, self.commit
            )
        )

        command = '{} && {}'.format(checkout_command, command)

        features = {}
        if artifacts:
            features['chainOfTrust'] = True
        if any(scope.startswith('secrets:') for scope in scopes):
            features['taskclusterProxy'] = True

        payload = {
            "features": features,
            "maxRunTime": 7200,
            "image": "mozillamobile/fenix:1.3",
            "command": [
                "/bin/bash",
                "--login",
                "-cx",
                command
            ],
            "artifacts": artifacts,
        }

        return self._craft_default_task_definition(
            'mobile-{}-b-fenix'.format(self.trust_level),
            'aws-provisioner-v1',
            dependencies,
            routes,
            scopes,
            name,
            description,
            payload,
            treeherder=treeherder,
        )

    def _craft_default_task_definition(
        self, worker_type, provisioner_id, dependencies, routes, scopes, name, description,
        payload, treeherder=None
    ):
        treeherder = {} if treeherder is None else treeherder

        created = datetime.datetime.now()
        deadline = taskcluster.fromNow('1 day')
        expires = taskcluster.fromNow(DEFAULT_EXPIRES_IN)

        return {
            "provisionerId": provisioner_id,
            "workerType": worker_type,
            "taskGroupId": self.task_id,
            "schedulerId": self.scheduler_id,
            "created": taskcluster.stringDate(created),
            "deadline": taskcluster.stringDate(deadline),
            "expires": taskcluster.stringDate(expires),
            "retries": 5,
            "tags": {},
            "priority": self.tasks_priority,
            "dependencies": [self.task_id] + dependencies,
            "requires": "all-completed",
            "routes": routes + [
                "tc-treeherder.v2.fenix.{}".format(self.commit)
            ],
            "scopes": scopes,
            "payload": payload,
            "extra": {
                "treeherder": treeherder,
            },
            "metadata": {
                "name": "Fenix - {}".format(name),
                "description": description,
                "owner": self.owner,
                "source": self.source,
            },
        }

    def craft_signing_task(
        self, build_task_id, apks, is_staging=True,
    ):
        signing_format = 'autograph_apk'
        payload = {
            "upstreamArtifacts": [{
                "paths": apks,
                "formats": [signing_format],
                "taskId": build_task_id,
                "taskType": "build",
            }],
        }

        index_release = 'staging-signed-nightly' if is_staging else 'signed-nightly'
        routes = [
            "index.project.mobile.fenix.{}.nightly.{}.{}.{}.latest".format(
                index_release, self.date.year, self.date.month, self.date.day
            ),
            "index.project.mobile.fenix.{}.nightly.{}.{}.{}.revision.{}".format(
                index_release, self.date.year, self.date.month, self.date.day, self.commit
            ),
            "index.project.mobile.fenix.{}.nightly.latest".format(index_release),
        ]

        return self._craft_default_task_definition(
            worker_type='mobile-signing-dep-v1' if is_staging else 'mobile-signing-v1',
            provisioner_id='scriptworker-prov-v1',
            dependencies=[build_task_id],
            routes=routes,
            scopes=[
                "project:mobile:fenix:releng:signing:format:{}".format(signing_format),
                "project:mobile:fenix:releng:signing:cert:{}".format(
                    'dep-signing' if is_staging else 'release-signing'
                )
            ],
            name="Signing task",
            description="Sign release builds of Fenix",
            payload=payload,
            treeherder={
                'jobKind': 'other',
                'machine': {
                  'platform': 'android-all',
                },
                'symbol': 'Ns',
                'tier': 1,
            },
        )

    def craft_push_task(
        self, signing_task_id, apks, is_staging=True
    ):
        payload = {
            "commit": True,
            "google_play_track": 'nightly',
            "upstreamArtifacts": [
                {
                    "paths": apks,
                    "taskId": signing_task_id,
                    "taskType": "signing"
                }
            ]
        }

        return self._craft_default_task_definition(
            worker_type='mobile-pushapk-dep-v1' if is_staging else 'mobile-pushapk-v1',
            provisioner_id='scriptworker-prov-v1',
            dependencies=[signing_task_id],
            routes=[],
            scopes=[
                "project:mobile:fenix:releng:googleplay:product:fenix{}".format(
                    ':dep' if is_staging else ''
                )
            ],
            name="Push task",
            description="Upload signed release builds of Fenix to Google Play",
            payload=payload,
            treeherder={
                'jobKind': 'other',
                'machine': {
                  'platform': 'android-all',
                },
                'symbol': 'gp',
                'tier': 1,
            },
        )


def _craft_treeherder_platform_from_variant(variant):
    architecture, build_type, _ = _get_architecture_and_build_type_and_product_from_variant(
        variant
    )
    return 'android-{}-{}'.format(architecture, build_type)


def _craft_treeherder_group_symbol_from_variant(variant):
    _, __, product = _get_architecture_and_build_type_and_product_from_variant(variant)
    return product


def _craft_artifacts_from_variant(variant):
    return {
        'public/target.apk': {
            'type': 'file',
            'path': _craft_apk_full_path_from_variant(variant),
            'expires': taskcluster.stringDate(taskcluster.fromNow(DEFAULT_EXPIRES_IN)),
        }
    }


def _craft_apk_full_path_from_variant(variant):
    architecture, build_type, product = _get_architecture_and_build_type_and_product_from_variant(
        variant
    )

    short_variant = variant[:-len(build_type)]
    postfix = '-unsigned' if build_type == 'release' else ''
    product = '{}{}'.format(product[0].lower(), product[1:])

    return '/opt/fenix/app/build/outputs/apk/{short_variant}/{build_type}/app-{architecture}-{product}-{build_type}{postfix}.apk'.format(     # noqa: E501
        architecture=architecture,
        build_type=build_type,
        product=product,
        short_variant=short_variant,
        postfix=postfix
    )


_SUPPORTED_ARCHITECTURES = ('aarch64', 'arm', 'x86')
_SUPPORTED_BUILD_TYPES = ('Debug', 'Release', 'ReleaseRaptor')
_SUPPORTED_PRODUCTS = ('FirefoxBeta', 'FirefoxNightly', 'FirefoxRelease', 'Greenfield')


def _get_architecture_and_build_type_and_product_from_variant(variant):
    for supported_architecture in _SUPPORTED_ARCHITECTURES:
        if variant.startswith(supported_architecture):
            architecture = supported_architecture
            break
    else:
        raise ValueError(
            'Cannot identify architecture in "{}". '
            'Expected to find one of these supported ones: {}'.format(
                variant, _SUPPORTED_ARCHITECTURES
            )
        )

    for supported_build_type in _SUPPORTED_BUILD_TYPES:
        if variant.endswith(supported_build_type):
            build_type = supported_build_type.lower()
            break
    else:
        raise ValueError(
            'Cannot identify build type in "{}". '
            'Expected to find one of these supported ones: {}'.format(
                variant, _SUPPORTED_BUILD_TYPES
            )
        )

    remaining_variant_data = variant[len(architecture):len(variant) - len(build_type)]
    for supported_product in _SUPPORTED_PRODUCTS:
        if remaining_variant_data == supported_product:
            product = supported_product
            break
    else:
        raise ValueError(
            'Cannot identify product in "{}" "{}". '
            'Expected to find one of these supported ones: {}'.format(
                remaining_variant_data, variant, _SUPPORTED_PRODUCTS
            )
        )

    return architecture, build_type, product


def schedule_task(queue, taskId, task):
    print("TASK", taskId)
    print(json.dumps(task, indent=4, separators=(',', ': ')))

    result = queue.createTask(taskId, task)
    print("RESULT", taskId)
    print(json.dumps(result))


def schedule_task_graph(ordered_groups_of_tasks):
    queue = taskcluster.Queue({'baseUrl': 'http://taskcluster/queue/v1'})
    full_task_graph = {}

    # TODO: Switch to async python to speed up submission
    for group_of_tasks in ordered_groups_of_tasks:
        for task_id, task_definition in group_of_tasks.items():
            schedule_task(queue, task_id, task_definition)

            full_task_graph[task_id] = {
                # Some values of the task definition are automatically filled. Querying the task
                # allows to have the full definition. This is needed to make Chain of Trust happy
                'task': queue.task(task_id),
            }
    return full_task_graph
