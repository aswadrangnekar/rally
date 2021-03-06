# Copyright 2014: Mirantis Inc.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import mock

from rally.benchmark.context import users
from rally import consts
from rally import exceptions
from rally import objects
from tests.unit import test


class UserGeneratorTestCase(test.TestCase):

    tenants_num = 1
    users_per_tenant = 5
    users_num = tenants_num * users_per_tenant
    threads = 10

    @property
    def context(self):
        return {
            "config": {
                "users": {
                    "tenants": self.tenants_num,
                    "users_per_tenant": self.users_per_tenant,
                    "resource_management_workers": self.threads,
                }
            },
            "admin": {"endpoint": mock.MagicMock()},
            "task": {"uuid": "task_id"}
        }

    def setUp(self):
        super(UserGeneratorTestCase, self).setUp()
        self.osclients_patcher = mock.patch(
            "rally.benchmark.context.users.osclients")
        self.osclients = self.osclients_patcher.start()

    def tearDown(self):
        self.osclients_patcher.stop()
        super(UserGeneratorTestCase, self).tearDown()

    @mock.patch("rally.benchmark.context.users.network.wrap")
    def test__remove_default_security_group_not_needed(self, mock_wrap):
        user_generator = users.UserGenerator(self.context)
        user_generator._remove_default_security_group()
        mock_wrap.assert_called_once_with(self.osclients.Clients.return_value)

    @mock.patch("rally.benchmark.context.users.network.wrap")
    def test__remove_default_security_group_neutron_no_sg(self, mock_wrap):
        net_wrapper = mock.Mock()
        net_wrapper.supports_security_group.return_value = (False, None)
        net_wrapper.SERVICE_IMPL = consts.Service.NEUTRON
        mock_wrap.return_value = net_wrapper

        user_generator = users.UserGenerator(self.context)

        admin_clients = mock.Mock()
        admin_clients.services.return_value = {"compute": consts.Service.NOVA}
        user_clients = [mock.Mock(), mock.Mock()]
        self.osclients.Clients.side_effect = [admin_clients] + user_clients

        user_generator._remove_default_security_group()

        mock_wrap.assert_called_once_with(admin_clients)
        net_wrapper.supports_security_group.assert_called_once_with()

    @mock.patch("rally.common.utils.iterate_per_tenants")
    @mock.patch("rally.benchmark.context.users.network")
    @mock.patch("rally.benchmark.utils.check_service_status",
                return_value=False)
    def test__remove_default_security_group(self, mock_check_service_status,
                                            mock_netwrap,
                                            mock_iterate_per_tenants):
        net_wrapper = mock.Mock()
        net_wrapper.supports_security_group.return_value = (True, None)
        net_wrapper.SERVICE_IMPL = consts.Service.NEUTRON
        mock_netwrap.wrap.return_value = net_wrapper

        user_generator = users.UserGenerator(self.context)

        admin_clients = mock.Mock()
        admin_clients.services.return_value = {"compute": consts.Service.NOVA}
        user_clients = [mock.Mock(), mock.Mock()]
        self.osclients.Clients.side_effect = [admin_clients] + user_clients

        mock_iterate_per_tenants.return_value = [
            (mock.MagicMock(), "t1"),
            (mock.MagicMock(), "t2")]

        user_generator._remove_default_security_group()

        mock_netwrap.wrap.assert_called_once_with(admin_clients)

        mock_iterate_per_tenants.assert_called_once_with(
            user_generator.context["users"])
        expected = [mock.call(user_generator.endpoint)] + [
            mock.call(u["endpoint"])
            for u, t in mock_iterate_per_tenants.return_value]
        self.osclients.Clients.assert_has_calls(expected, any_order=True)

        expected_deletes = []
        for clients in user_clients:
            user_nova = clients.nova.return_value
            user_nova.security_groups.find.assert_called_once_with(
                name="default")
            expected_deletes.append(
                mock.call(user_nova.security_groups.find.return_value.id))

        nova_admin = admin_clients.neutron.return_value
        nova_admin.delete_security_group.assert_has_calls(expected_deletes,
                                                          any_order=True)

    @mock.patch("rally.benchmark.utils.check_service_status",
                return_value=True)
    def test__remove_associated_networks(self, mock_check_service_status):
        def fake_get_network(req_network):
            for network in networks:
                if network.project_id == req_network.project_id:
                    return network

        networks = [mock.MagicMock(project_id="t1"),
                    mock.MagicMock(project_id="t4")]
        nova_admin = mock.MagicMock()
        clients = mock.MagicMock()
        self.osclients.Clients.return_value = clients
        clients.services.return_value = {"compute": "nova"}
        clients.nova.return_value = nova_admin
        nova_admin.networks.list.return_value = networks
        nova_admin.networks.get = fake_get_network
        user_generator = users.UserGenerator(self.context)
        user_generator.context["tenants"] = {"t1": dict(id="t1", name="t1"),
                                             "t2": dict(id="t2", name="t2")}
        user_generator._remove_associated_networks()
        mock_check_service_status.assert_called_once_with(mock.ANY,
                                                          "nova-network")
        nova_admin.networks.disassociate.assert_called_once_with(networks[0])

    @mock.patch("rally.benchmark.utils.check_service_status",
                return_value=True)
    def test__remove_associated_networks_failure(self,
                                                 mock_check_service_status):
        def fake_get_network(req_network):
            for network in networks:
                if network.project_id == req_network.project_id:
                    return network

        networks = [mock.MagicMock(project_id="t1"),
                    mock.MagicMock(project_id="t4")]
        nova_admin = mock.MagicMock()
        clients = mock.MagicMock()
        self.osclients.Clients.return_value = clients
        clients.services.return_value = {"compute": "nova"}
        clients.nova.return_value = nova_admin
        nova_admin.networks.list.return_value = networks
        nova_admin.networks.get = fake_get_network
        nova_admin.networks.disassociate.side_effect = Exception()
        user_generator = users.UserGenerator(self.context)
        user_generator.context["tenants"] = {"t1": dict(id="t1", name="t1"),
                                             "t2": dict(id="t2", name="t2")}
        user_generator._remove_associated_networks()
        mock_check_service_status.assert_called_once_with(mock.ANY,
                                                          "nova-network")
        nova_admin.networks.disassociate.assert_called_once_with(networks[0])

    @mock.patch("rally.benchmark.context.users.broker.time.sleep")
    @mock.patch("rally.benchmark.context.users.keystone")
    def test__create_tenants(self, mock_keystone, mock_sleep):
        user_generator = users.UserGenerator(self.context)
        user_generator.config["tenants"] = 1
        tenants = user_generator._create_tenants()
        self.assertEqual(1, len(tenants))
        id, tenant = tenants.popitem()
        self.assertIn("name", tenant)

    @mock.patch("rally.benchmark.context.users.broker.time.sleep")
    @mock.patch("rally.benchmark.context.users.keystone")
    def test__create_users(self, mock_keystone, mock_sleep):
        user_generator = users.UserGenerator(self.context)
        user_generator.context["tenants"] = {"t1": dict(id="t1", name="t1"),
                                             "t2": dict(id="t2", name="t2")}
        user_generator.config["users_per_tenant"] = 2
        users_ = user_generator._create_users()
        self.assertEqual(4, len(users_))
        for user in users_:
            self.assertIn("id", user)
            self.assertIn("endpoint", user)

    @mock.patch("rally.benchmark.context.users.keystone")
    def test__delete_tenants(self, mock_keystone):
        user_generator = users.UserGenerator(self.context)
        user_generator.context["tenants"] = {"t1": dict(id="t1", name="t1"),
                                             "t2": dict(id="t2", name="t2")}
        user_generator._delete_tenants()
        self.assertEqual(len(user_generator.context["tenants"]), 0)

    @mock.patch("rally.benchmark.context.users.keystone")
    def test__delete_tenants_failure(self, mock_keystone):
        wrapped_keystone = mock_keystone.wrap.return_value
        wrapped_keystone.delete_project.side_effect = Exception()
        user_generator = users.UserGenerator(self.context)
        user_generator.context["tenants"] = {"t1": dict(id="t1", name="t1"),
                                             "t2": dict(id="t2", name="t2")}
        user_generator._delete_tenants()
        self.assertEqual(len(user_generator.context["tenants"]), 0)

    @mock.patch("rally.benchmark.context.users.keystone")
    def test__delete_users(self, mock_keystone):
        user_generator = users.UserGenerator(self.context)
        user1 = mock.MagicMock()
        user2 = mock.MagicMock()
        user_generator.context["users"] = [user1, user2]
        user_generator._delete_users()
        self.assertEqual(len(user_generator.context["users"]), 0)

    @mock.patch("rally.benchmark.context.users.keystone")
    def test__delete_users_failure(self, mock_keystone):
        wrapped_keystone = mock_keystone.wrap.return_value
        wrapped_keystone.delete_user.side_effect = Exception()
        user_generator = users.UserGenerator(self.context)
        user1 = mock.MagicMock()
        user2 = mock.MagicMock()
        user_generator.context["users"] = [user1, user2]
        user_generator._delete_users()
        self.assertEqual(len(user_generator.context["users"]), 0)

    @mock.patch("rally.benchmark.context.users.keystone")
    def test_setup_and_cleanup(self, mock_keystone):
        wrapped_keystone = mock.MagicMock()
        mock_keystone.wrap.return_value = wrapped_keystone
        with users.UserGenerator(self.context) as ctx:

            ctx.setup()

            self.assertEqual(len(ctx.context["users"]),
                             self.users_num)
            self.assertEqual(len(ctx.context["tenants"]),
                             self.tenants_num)

        # Cleanup (called by content manager)
        self.assertEqual(len(ctx.context["users"]), 0)
        self.assertEqual(len(ctx.context["tenants"]), 0)

    @mock.patch("rally.benchmark.context.users.keystone")
    def test_setup_and_cleanup_failure(self, mock_keystone):
        wrapped_keystone = mock_keystone.wrap.return_value
        wrapped_keystone.create_user.side_effect = Exception()
        with users.UserGenerator(self.context) as ctx:
            self.assertRaises(exceptions.ContextSetupFailure, ctx.setup)

        # Ensure that tenants get deleted anyway
        self.assertEqual(len(ctx.context["tenants"]), 0)

    @mock.patch("rally.benchmark.context.users.keystone")
    def test_users_and_tenants_in_context(self, mock_keystone):
        wrapped_keystone = mock.MagicMock()
        mock_keystone.wrap.return_value = wrapped_keystone
        task = {"uuid": "abcdef"}

        config = {
            "config": {
                "users": {
                    "tenants": 1,
                    "users_per_tenant": 2,
                    "resource_management_workers": 1
                }
            },
            "admin": {"endpoint": mock.MagicMock()},
            "task": task
        }

        user_list = [mock.MagicMock(id="id_%d" % i)
                     for i in range(self.users_num)]
        wrapped_keystone.create_user.side_effect = user_list

        with users.UserGenerator(config) as ctx:
            ctx.setup()

            create_tenant_calls = []
            for i, t in enumerate(ctx.context["tenants"]):
                pattern = users.UserGenerator.PATTERN_TENANT
                create_tenant_calls.append(
                    mock.call(pattern % {"task_id": task["uuid"], "iter": i},
                              ctx.config["project_domain"]))

            for user in ctx.context["users"]:
                self.assertEqual(set(["id", "endpoint", "tenant_id"]),
                                 set(user.keys()))

            tenants_ids = []
            for t in ctx.context["tenants"].keys():
                tenants_ids.append(t)

            for (user, tenant_id, orig_user) in zip(ctx.context["users"],
                                                    tenants_ids, user_list):
                self.assertEqual(user["id"], orig_user.id)
                self.assertEqual(user["tenant_id"], tenant_id)

    @mock.patch("rally.benchmark.context.users.keystone")
    def test_users_contains_correct_endpoint_type(self, mock_keystone):
        endpoint = objects.Endpoint("foo_url", "foo", "foo_pass",
                                    endpoint_type=consts.EndpointType.INTERNAL)
        config = {
            "config": {
                "users": {
                    "tenants": 1,
                    "users_per_tenant": 2,
                    "resource_management_workers": 1
                }
            },
            "admin": {"endpoint": endpoint},
            "task": {"uuid": "task_id"}
        }

        user_generator = users.UserGenerator(config)
        users_ = user_generator._create_users()

        for user in users_:
            self.assertEqual("internal", user["endpoint"].endpoint_type)

    @mock.patch("rally.benchmark.context.users.keystone")
    def test_users_contains_default_endpoint_type(self, mock_keystone):
        endpoint = objects.Endpoint("foo_url", "foo", "foo_pass")
        config = {
            "config": {
                "users": {
                    "tenants": 1,
                    "users_per_tenant": 2,
                    "resource_management_workers": 1
                }
            },
            "admin": {"endpoint": endpoint},
            "task": {"uuid": "task_id"}
        }

        user_generator = users.UserGenerator(config)
        users_ = user_generator._create_users()

        for user in users_:
            self.assertEqual("public", user["endpoint"].endpoint_type)
