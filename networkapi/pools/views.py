# -*- coding:utf-8 -*-

# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License.  You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
from django.core.exceptions import ObjectDoesNotExist

from django.db.transaction import commit_on_success
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework import status
from rest_framework.response import Response
from networkapi.ip.models import IpEquipamento
from networkapi.equipamento.models import Equipamento
from networkapi.requisicaovips.models import ServerPool, ServerPoolMember, \
    VipPortToPool
from networkapi.pools.serializers import ServerPoolSerializer, HealthcheckSerializer, \
    ServerPoolMemberSerializer, ServerPoolDatatableSerializer, EquipamentoSerializer, OpcaoPoolAmbienteSerializer, \
    VipPortToPoolSerializer, PoolSerializer
from networkapi.healthcheckexpect.models import Healthcheck
from networkapi.ambiente.models import Ambiente, EnvironmentVip
from networkapi.ip.models import Ip, Ipv6
from networkapi.infrastructure.datatable import build_query_to_datatable
from networkapi.api_rest import exceptions as api_exceptions
from networkapi.util import is_valid_list_int_greater_zero_param, \
    is_valid_int_greater_zero_param
from networkapi.log import Log
from networkapi.pools import exceptions
from networkapi.pools.permissions import Read, Write, ScriptRemovePermission, \
    ScriptCreatePermission, ScriptAlterPermission
from networkapi.infrastructure.script_utils import exec_script, ScriptError
from networkapi.settings import POOL_REMOVE, POOL_CREATE, POOL_REAL_CREATE, \
    POOL_REAL_REMOVE, POOL_REAL_ENABLE, POOL_REAL_DISABLE
from networkapi.pools.models import OpcaoPool, OpcaoPoolAmbiente
from networkapi.requisicaovips.models import RequisicaoVips

log = Log(__name__)


@api_view(['POST'])
@permission_classes((IsAuthenticated, Read))
@commit_on_success
def pool_list(request):
    """
    List all code snippets, or create a new snippet.
    """
    try:

        data = dict()

        environment_id = request.DATA.get("environment_id")
        start_record = request.DATA.get("start_record")
        end_record = request.DATA.get("end_record")
        asorting_cols = request.DATA.get("asorting_cols")
        searchable_columns = request.DATA.get("searchable_columns")
        custom_search = request.DATA.get("custom_search")

        if not is_valid_int_greater_zero_param(environment_id, False):
            raise api_exceptions.ValidationException('Environment id invalid.')

        query_pools = ServerPool.objects.all()

        if environment_id:
            query_pools = query_pools.filter(environment=environment_id)

        server_pools, total = build_query_to_datatable(
            query_pools,
            asorting_cols,
            custom_search,
            searchable_columns,
            start_record,
            end_record
        )

        serializer_pools = ServerPoolDatatableSerializer(
            server_pools,
            many=True
        )

        data["pools"] = serializer_pools.data
        data["total"] = total

        return Response(data)

    except api_exceptions.ValidationException, exception:
        log.error(exception)
        raise exception

    except Exception, exception:
        log.error(exception)
        raise api_exceptions.NetworkAPIException()


@api_view(['POST'])
@permission_classes((IsAuthenticated, Read))
@commit_on_success
def list_all_members_by_pool(request, id_server_pool):

    try:

        if not is_valid_int_greater_zero_param(id_server_pool):
            raise exceptions.InvalidIdPoolException()

        data = dict()
        start_record = request.DATA.get("start_record")
        end_record = request.DATA.get("end_record")
        asorting_cols = request.DATA.get("asorting_cols")
        searchable_columns = request.DATA.get("searchable_columns")
        custom_search = request.DATA.get("custom_search")

        query_pools = ServerPoolMember.objects.filter(server_pool=id_server_pool)

        server_pools, total = build_query_to_datatable(
            query_pools,
            asorting_cols,
            custom_search,
            searchable_columns,
            start_record,
            end_record
        )

        serializer_pools = ServerPoolMemberSerializer(server_pools, many=True)

        data["server_pool_members"] = serializer_pools.data
        data["total"] = total

        return Response(data)

    except exceptions.InvalidIdPoolException, exception:
        log.error(exception)
        raise exception

    except ServerPool.DoesNotExist, exception:
        log.error(exception)
        raise exceptions.PoolDoesNotExistException()

    except Exception, exception:
        log.error(exception)
        raise api_exceptions.NetworkAPIException()


@api_view(['GET'])
@permission_classes((IsAuthenticated, Read))
@commit_on_success
def get_equipamento_by_ip(request, id_ip):

    try:

        if not is_valid_int_greater_zero_param(id_ip):
            raise exceptions.InvalidIdPoolException()

        data = dict()

        ipequips_obj = IpEquipamento.objects.filter(ip=id_ip).uniqueResult()
        equip = Equipamento.get_by_pk(pk=ipequips_obj.equipamento_id)

        serializer_equipamento = EquipamentoSerializer(equip, many=False)

        data["equipamento"] = serializer_equipamento.data

        return Response(data)

    except exceptions.InvalidIdPoolException, exception:
        log.error(exception)
        raise exception

    except Exception, exception:
        log.error(exception)
        raise api_exceptions.NetworkAPIException()


@api_view(['POST'])
@permission_classes((IsAuthenticated, Write, ScriptAlterPermission))
@commit_on_success
def delete(request):
    """
    Delete Pools by list id.
    """

    try:

        ids = request.DATA.get('ids')

        is_valid_list_int_greater_zero_param(ids)

        for _id in ids:
            try:
                server_pool = ServerPool.objects.get(id=_id)

                if VipPortToPool.objects.filter(server_pool=_id):
                    raise exceptions.PoolConstraintVipException()

                for server_pool_member in server_pool.serverpoolmember_set.all():

                    ipv4 = server_pool_member.ip
                    ipv6 = server_pool_member.ipv6

                    id_pool = server_pool.id
                    id_ip = ipv4 and ipv4.id or ipv6 and ipv6.id
                    port_ip = server_pool_member.port_real

                    server_pool_member.delete(request.user)

                    command = POOL_REAL_REMOVE % (id_pool, id_ip, port_ip)

                    code, _, _ = exec_script(command)

                    if code != 0:
                        raise exceptions.ScriptDeletePoolException()

                server_pool.delete(request.user)

            except ServerPool.DoesNotExist:
                pass

        return Response(status=status.HTTP_204_NO_CONTENT)

    except exceptions.PoolConstraintVipException, exception:
        log.error(exception)
        raise exception

    except exceptions.ScriptDeletePoolException, exception:
        log.error(exception)
        raise exception

    except ScriptError, exception:
        log.error(exception)
        raise exceptions.ScriptDeletePoolException()

    except ValueError, exception:
        log.error(exception)
        raise exceptions.InvalidIdPoolException()

    except Exception, exception:
        log.error(exception)
        raise api_exceptions.NetworkAPIException()


@api_view(['POST'])
@permission_classes((IsAuthenticated, ScriptRemovePermission))
@commit_on_success
def remove(request):
    """
    Remove Pools by list id running script and update to not created.
    """

    try:

        ids = request.DATA.get('ids')

        is_valid_list_int_greater_zero_param(ids)

        for _id in ids:
            try:

                server_pool = ServerPool.objects.get(id=_id)

                code, _, _ = exec_script(POOL_REMOVE % _id)

                if code != 0:
                    raise exceptions.ScriptRemovePoolException()

                server_pool.pool_created = False
                server_pool.save(request.user)

            except ServerPool.DoesNotExist:
                pass

        return Response()

    except exceptions.ScriptRemovePoolException, exception:
        log.error(exception)
        raise exception

    except ScriptError, exception:
        log.error(exception)
        raise exceptions.ScriptRemovePoolException()

    except ValueError, exception:
        log.error(exception)
        raise exceptions.InvalidIdPoolException()

    except Exception, exception:
        log.error(exception)
        raise api_exceptions.NetworkAPIException()


@api_view(['POST'])
@permission_classes((IsAuthenticated, Write, ScriptCreatePermission))
@commit_on_success
def create(request):
    """
    Create Pools by list id running script and update to created.
    """

    try:

        ids = request.DATA.get('ids')

        is_valid_list_int_greater_zero_param(ids)

        for _id in ids:

            server_pool = ServerPool.objects.get(id=_id)

            code, _, _ = exec_script(POOL_CREATE % _id)

            if code != 0:
                raise exceptions.ScriptCreatePoolException()

            server_pool.pool_created = True
            server_pool.save(request.user)

        return Response()

    except ServerPool.DoesNotExist, exception:
        log.error(exception)
        raise exceptions.PoolDoesNotExistException()

    except exceptions.ScriptCreatePoolException, exception:
        log.error(exception)
        raise exception

    except ScriptError, exception:
        log.error(exception)
        raise exceptions.ScriptCreatePoolException()

    except ValueError, exception:
        log.error(exception)
        raise exceptions.InvalidIdPoolException()

    except Exception, exception:
        log.error(exception)
        raise api_exceptions.NetworkAPIException()


@api_view(['GET'])
@permission_classes((IsAuthenticated, Read))
@commit_on_success
def healthcheck_list(request):

    try:
        data = dict()

        healthchecks = Healthcheck.objects.all()

        serializer_healthchecks = HealthcheckSerializer(
            healthchecks,
            many=True
        )

        data["healthchecks"] = serializer_healthchecks.data

        return Response(data)

    except Exception, exception:
        log.error(exception)
        raise api_exceptions.NetworkAPIException()


@api_view(['GET'])
@permission_classes((IsAuthenticated, Read))
@commit_on_success
def get_by_pk(request, id_server_pool):

    try:

        if not is_valid_int_greater_zero_param(id_server_pool):
            raise exceptions.InvalidIdPoolException()

        data = dict()

        server_pool = ServerPool.objects.get(pk=id_server_pool)

        server_pool_members = ServerPoolMember.objects.filter(
            server_pool=id_server_pool
        )

        serializer_server_pool = ServerPoolSerializer(server_pool)

        serializer_server_pool_member = ServerPoolMemberSerializer(
            server_pool_members,
            many=True
        )

        data["server_pool"] = serializer_server_pool.data
        data["server_pool_members"] = serializer_server_pool_member.data

        return Response(data)

    except exceptions.InvalidIdPoolException, exception:
        log.error(exception)
        raise exception

    except ServerPool.DoesNotExist, exception:
        log.error(exception)
        raise exceptions.PoolDoesNotExistException()

    except Exception, exception:
        log.error(exception)
        raise api_exceptions.NetworkAPIException()


@api_view(['POST'])
@permission_classes((IsAuthenticated, Write, ScriptAlterPermission))
@commit_on_success
def pool_insert(request):

    try:
        # TODO: ADD VALIDATION
        identifier = request.DATA.get('identifier')
        default_port = request.DATA.get('default_port')
        environment = request.DATA.get('environment')
        balancing = request.DATA.get('balancing')
        maxcom = request.DATA.get('maxcom')
        ip_list_full = request.DATA.get('ip_list_full')
        priorities = request.DATA.get('priorities')
        ports_reals = request.DATA.get('ports_reals')


        has_identifier = ServerPool.objects.filter(identifier=identifier).count()

        if has_identifier > 0:
            raise exceptions.InvalidIdentifierPoolException()



        # ADDING AND VERIFYING HEALTHCHECK ------------------------------------------------------
        healthcheck_type = request.DATA.get('healthcheck_type')
        healthcheck_request = request.DATA.get('healthcheck_request')
        healthcheck_expect = request.DATA.get('healthcheck_expect')
        old_healthcheck_id = request.DATA.get('old_healthcheck_id')

        try:
            # Query HealthCheck table for one equal this
            hc = Healthcheck.objects.get(healthcheck_expect=healthcheck_expect, healthcheck_type=healthcheck_type, healthcheck_request=healthcheck_request)

        # Else, add a new one
        except ObjectDoesNotExist:

            hc = Healthcheck(
                identifier='',
                healthcheck_type=healthcheck_type,
                healthcheck_request=healthcheck_request,
                healthcheck_expect=healthcheck_expect,
                destination=''
            )

            hc.save(request.user)

        # ---------------------------------------------------------------------------------------


        ambiente_obj = Ambiente.get_by_pk(environment)

        sp = ServerPool(
            identifier=identifier,
            default_port=default_port,
            healthcheck=hc,
            environment=ambiente_obj,
            pool_created=False,
            lb_method=balancing
        )

        sp.save(request.user)

        # Check if someone is using the old healthcheck
        # If not, delete it to keep the database clean
        if old_healthcheck_id is not None:
            pools_using_healthcheck = ServerPool.objects.filter(healthcheck=old_healthcheck_id).count()

            if pools_using_healthcheck == 0:
                Healthcheck.objects.get(id=old_healthcheck_id).delete(request.user)

        ip_object = None
        ipv6_object = None

        for i in range(0, len(ip_list_full)):

            if len(ip_list_full[i]['ip']) <= 15:
                ip_object = Ip.get_by_pk(ip_list_full[i]['id'])
            else:
                ipv6_object = Ipv6.get_by_pk(ip_list_full[i]['id'])

            spm = ServerPoolMember(
                server_pool=sp,
                identifier=identifier,
                ip=ip_object,
                ipv6=ipv6_object,
                priority=priorities[i],
                weight=0,
                limit=maxcom,
                port_real=ports_reals[i],
                healthcheck=hc
            )

            spm.save(request.user)

            id_pool = sp.id
            id_ip = ip_object and ip_object.id or ipv6_object and ipv6_object.id
            port_ip = spm.port_real

            command = POOL_REAL_CREATE % (id_pool, id_ip, port_ip)

            code, _, _ = exec_script(command)

            if code != 0:
                raise exceptions.ScriptAddPoolException()

        return Response(status=status.HTTP_201_CREATED)

    except exceptions.ScriptAddPoolException, exception:
        log.error(exception)
        raise exception

    except exceptions.InvalidIdentifierPoolException, exception:
        log.error(exception)
        raise exception

    except Exception, exception:
        log.error(exception)
        raise api_exceptions.NetworkAPIException()


@api_view(['POST'])
@permission_classes((IsAuthenticated, Write, ScriptAlterPermission))
@commit_on_success
def pool_edit(request):

    try:

        id_server_pool = request.DATA.get('id_server_pool')

        if not is_valid_int_greater_zero_param(id_server_pool):
            raise exceptions.InvalidIdPoolException()

        identifier = request.DATA.get('identifier')
        default_port = request.DATA.get('default_port')
        # environment = request.DATA.get('environment')
        balancing = request.DATA.get('balancing')
        maxcom = request.DATA.get('maxcom')
        ip_list_full = request.DATA.get('ip_list_full')
        priorities = request.DATA.get('priorities')
        ports_reals = request.DATA.get('ports_reals')


        # ADDING AND VERIFYING HEALTHCHECK ------------------------------------------------------
        healthcheck_type = request.DATA.get('healthcheck_type')
        healthcheck_request = request.DATA.get('healthcheck_request')
        healthcheck_expect = request.DATA.get('healthcheck_expect')
        old_healthcheck_id = request.DATA.get('old_healthcheck_id')

        try:
            # Query HealthCheck table for one equal this
            hc = Healthcheck.objects.get(healthcheck_expect=healthcheck_expect, healthcheck_type=healthcheck_type, healthcheck_request=healthcheck_request)

        # Else, add a new one
        except ObjectDoesNotExist:

            hc = Healthcheck(
                identifier='',
                healthcheck_type=healthcheck_type,
                healthcheck_request=healthcheck_request,
                healthcheck_expect=healthcheck_expect,
                destination=''
            )

            hc.save(request.user)

        # ---------------------------------------------------------------------------------------

        # ambiente_obj = Ambiente.get_by_pk(environment)

        sp = ServerPool.objects.get(id=id_server_pool)
        sp.default_port = default_port
        sp.healthcheck = hc
        sp.lb_method = balancing

        sp.save(request.user)

        # Check if someone is using the old healthcheck
        # If not, delete it to keep the database clean
        if old_healthcheck_id is not None:
            pools_using_healthcheck = ServerPool.objects.filter(healthcheck=old_healthcheck_id).count()

            if pools_using_healthcheck == 0:
                Healthcheck.objects.get(id=old_healthcheck_id).delete(request.user)

        # Excludes all ServerPoolMembers of this ServerPool so we can re-add them
        spm_list = ServerPoolMember.objects.filter(server_pool=sp)

        for spm in spm_list:
            spm.delete(request.user)

        ip_object = None
        ipv6_object = None

        for i in range(0, len(ip_list_full)):
            if len(ip_list_full[i]['ip']) <= 15:
                ip_object = Ip.get_by_pk(ip_list_full[i]['id'])
            else:
                ipv6_object = Ipv6.get_by_pk(ip_list_full[i]['id'])

            spm = ServerPoolMember(
                server_pool=sp,
                identifier=identifier,
                ip=ip_object,
                ipv6=ipv6_object,
                priority=priorities[i],
                weight=0,
                limit=maxcom,
                port_real=ports_reals[i],
                healthcheck=hc
            )

            spm.save(request.user)

        return Response()

    except exceptions.InvalidIdPoolException, exception:
        log.error(exception)
        raise exception

    except ServerPool.DoesNotExist, exception:
        log.error(exception)
        raise exceptions.PoolDoesNotExistException()

    except Exception, exception:
        log.error(exception)
        raise api_exceptions.NetworkAPIException()


@api_view(['POST'])
@permission_classes((IsAuthenticated, ScriptAlterPermission))
@commit_on_success
def enable(request):
    """
    Create Pools by list id running script and update to created.
    """

    try:

        ids = request.DATA.get('ids')

        is_valid_list_int_greater_zero_param(ids)

        for _id in ids:

            server_pool_member = ServerPoolMember.objects.get(id=_id)

            ipv4 = server_pool_member.ip
            ipv6 = server_pool_member.ipv6

            id_pool = server_pool_member.server_pool.id
            id_ip = ipv4 and ipv4.id or ipv6 and ipv6.id
            port_ip = server_pool_member.port_real

            command = POOL_REAL_ENABLE % (id_pool, id_ip, port_ip)

            code, _, _ = exec_script(command)

            if code != 0:
                raise exceptions.ScriptEnablePoolException()

        return Response()

    except ServerPoolMember.DoesNotExist, exception:
        log.error(exception)
        raise exceptions.PoolMemberDoesNotExistException()

    except exceptions.ScriptEnablePoolException, exception:
        log.error(exception)
        raise exception

    except ScriptError, exception:
        log.error(exception)
        raise exceptions.ScriptEnablePoolException()

    except ValueError, exception:
        log.error(exception)
        raise exceptions.InvalidIdPoolMemberException()

    except Exception, exception:
        log.error(exception)
        raise api_exceptions.NetworkAPIException()


@api_view(['POST'])
@permission_classes((IsAuthenticated, ScriptAlterPermission))
@commit_on_success
def disable(request):
    """
    Create Pools by list id running script and update to created.
    """

    try:

        ids = request.DATA.get('ids')

        is_valid_list_int_greater_zero_param(ids)

        for _id in ids:

            server_pool_member = ServerPoolMember.objects.get(id=_id)

            ipv4 = server_pool_member.ip
            ipv6 = server_pool_member.ipv6

            id_pool = server_pool_member.server_pool.id
            id_ip = ipv4 and ipv4.id or ipv6 and ipv6.id
            port_ip = server_pool_member.port_real

            command = POOL_REAL_DISABLE % (id_pool, id_ip, port_ip)

            code, _, _ = exec_script(command)

            if code != 0:
                raise exceptions.ScriptDisablePoolException()

        return Response()

    except ServerPoolMember.DoesNotExist, exception:
        log.error(exception)
        raise exceptions.PoolMemberDoesNotExistException()

    except exceptions.ScriptDisablePoolException, exception:
        log.error(exception)
        raise exception

    except ScriptError, exception:
        log.error(exception)
        raise exceptions.ScriptDisablePoolException()

    except ValueError, exception:
        log.error(exception)
        raise exceptions.InvalidIdPoolMemberException()

    except Exception, exception:
        log.error(exception)
        raise api_exceptions.NetworkAPIException()


@api_view(['GET', 'POST'])
@permission_classes((IsAuthenticated, Read))
@commit_on_success
def get_opcoes_pool_by_ambiente(request):

    try:

        id_ambiente = request.DATA.get('id_environment')

        data = dict()

        is_valid_int_greater_zero_param(id_ambiente)
        query_opcoes = OpcaoPoolAmbiente.objects.filter(ambiente=id_ambiente)
        opcoes_serializer = OpcaoPoolAmbienteSerializer(query_opcoes, many=True)
        data['opcoes_pool'] = opcoes_serializer.data

        return Response(data)

    except Exception, exception:
        log.error(exception)
        raise api_exceptions.NetworkAPIException()


@api_view(['GET'])
@permission_classes((IsAuthenticated, Read))
@commit_on_success
def list_by_environment(request, environment_id):

    try:

        data = dict()

        created = True

        if not is_valid_int_greater_zero_param(environment_id):
            raise api_exceptions.ValidationException('Environment id invalid.')

        environment_obj = Ambiente.objects.get(id=environment_id)

        query_pools = ServerPool.objects.filter(
            environment=environment_obj,
            pool_created=created
        )

        serializer_pools = ServerPoolDatatableSerializer(
            query_pools,
            many=True
        )

        data["pools"] = serializer_pools.data

        return Response(data)

    except Ambiente.DoesNotExist, exception:
        log.error(exception)
        raise api_exceptions.ObjectDoesNotExistException('Environment Does Not Exist.')

    except api_exceptions.ValidationException, exception:
        log.error(exception)
        raise exception

    except Exception, exception:
        log.error(exception)
        raise api_exceptions.NetworkAPIException()


@api_view(['GET', 'POST'])
@permission_classes((IsAuthenticated, Read))
@commit_on_success
def get_requisicoes_vip_by_pool(request, id_server_pool):

    try:
        data = dict()

        if not is_valid_int_greater_zero_param(id_server_pool):
            raise exceptions.InvalidIdPoolException()

        start_record = request.DATA.get("start_record")
        end_record = request.DATA.get("end_record")
        asorting_cols = request.DATA.get("asorting_cols")
        searchable_columns = request.DATA.get("searchable_columns")
        custom_search = request.DATA.get("custom_search")

        query_requisicoes = VipPortToPool.objects.filter(server_pool=id_server_pool)

        requisicoes, total = build_query_to_datatable(
            query_requisicoes,
            asorting_cols,
            custom_search,
            searchable_columns,
            start_record,
            end_record
        )

        requisicoes_serializer = VipPortToPoolSerializer(requisicoes, many=True)

        data['requisicoes_vip'] = requisicoes_serializer.data
        data['total'] = total

        return Response(data)

    except Exception, exception:
        log.error(exception)
        raise api_exceptions.NetworkAPIException()


@api_view(['GET'])
@permission_classes((IsAuthenticated, Read))
@commit_on_success
def list_pool_members(request, pool_id):

    try:

        data = dict()

        if not is_valid_int_greater_zero_param(pool_id):
            raise exceptions.InvalidIdPoolException()

        pool_obj = ServerPool.objects.get(id=pool_id)

        query_pools = ServerPoolMember.objects.filter(server_pool=pool_obj)

        serializer_pools = ServerPoolMemberSerializer(query_pools, many=True)

        data["pool_members"] = serializer_pools.data

        return Response(data)

    except exceptions.InvalidIdPoolException, exception:
        log.error(exception)
        raise exception

    except ServerPool.DoesNotExist, exception:
        log.error(exception)
        raise exceptions.PoolDoesNotExistException()

    except Exception, exception:
        log.error(exception)
        raise api_exceptions.NetworkAPIException()


@api_view(['GET'])
@permission_classes((IsAuthenticated, Read))
@commit_on_success
def list_by_environment_vip(request, environment_vip_id):

    try:

        env_vip = EnvironmentVip.objects.get(id=environment_vip_id)

        server_pool_query = ServerPool.objects.filter(
            environment__vlan__networkipv4__ambient_vip=env_vip
        ).order_by('identifier')

        serializer_pools = PoolSerializer(server_pool_query, many=True)

        return Response(serializer_pools.data)

    except EnvironmentVip.DoesNotExist, exception:
        log.error(exception)
        raise api_exceptions.ObjectDoesNotExistException('Environment Vip Does Not Exist')

    except Exception, exception:
        log.error(exception)
        raise api_exceptions.NetworkAPIException()