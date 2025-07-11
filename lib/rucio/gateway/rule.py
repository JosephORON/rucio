# Copyright European Organization for Nuclear Research (CERN) since 2012
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from typing import TYPE_CHECKING, Any, Literal, Optional

from rucio.common.config import config_get_bool
from rucio.common.constants import DEFAULT_VO
from rucio.common.exception import AccessDenied
from rucio.common.schema import validate_schema
from rucio.common.types import InternalAccount, InternalScope
from rucio.common.utils import gateway_update_return_dict
from rucio.core import rule
from rucio.db.sqla.constants import DatabaseOperationType
from rucio.db.sqla.session import db_session
from rucio.gateway.permission import has_permission

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

    from sqlalchemy.orm import Session


def is_multi_vo(session: "Session") -> bool:
    """
    Check whether this instance is configured for multi-VO
    returns: Boolean True if running in multi-VO
    """
    return config_get_bool('common', 'multi_vo', raise_exception=False, default=False, session=session)


def add_replication_rule(
    dids: "Sequence[dict[str, str]]",
    copies: int,
    rse_expression: str,
    weight: Optional[str],
    lifetime: Optional[int],
    grouping: Literal['ALL', 'DATASET', 'NONE'],
    account: str,
    locked: bool,
    subscription_id: Optional[str],
    source_replica_expression: Optional[str],
    activity: Optional[str],
    notify: Optional[Literal['Y', 'N', 'C', 'P']],
    purge_replicas: bool,
    ignore_availability: bool,
    comment: Optional[str],
    ask_approval: bool,
    asynchronous: bool,
    delay_injection: Optional[int],
    priority: int,
    split_container: bool,
    meta: Optional[dict[str, Any]],
    issuer: str,
    vo: str = DEFAULT_VO,
) -> list[str]:
    """
    Adds a replication rule.

    :param dids:                       The data identifier set.
    :param copies:                     The number of replicas.
    :param rse_expression:             Boolean string expression to give the list of RSEs.
    :param weight:                     If the weighting option of the replication rule is used, the choice of RSEs takes their weight into account.
    :param lifetime:                   The lifetime of the replication rules (in seconds).
    :param grouping:                   ALL -  All files will be replicated to the same RSE.
                                       DATASET - All files in the same dataset will be replicated to the same RSE.
                                       NONE - Files will be completely spread over all allowed RSEs without any grouping considerations at all.
    :param account:                    The account owning the rule.
    :param locked:                     If the rule is locked, it cannot be deleted.
    :param subscription_id:            The subscription_id, if the rule is created by a subscription.
    :param source_replica_expression:  Only use replicas from this RSE as sources.
    :param activity:                   Activity to be passed on to the conveyor.
    :param notify:                     Notification setting of the rule.
    :purge purge_replicas:             The purge setting to delete replicas immediately after rule deletion.
    :param ignore_availability:        Option to ignore the availability of RSEs.
    :param comment:                    Comment about the rule.
    :param ask_approval:               Ask for approval of this rule.
    :param asynchronous:               Create rule asynchronously by judge-injector.
    :param priority:                   Priority of the transfers.
    :param split_container:            Should a container rule be split into individual dataset rules.
    :param meta:                       WFMS metadata as a dictionary.
    :param issuer:                     The issuing account of this operation.
    :param vo:                         The VO to act on.
    :returns:                          List of created replication rules.
    """
    if account is None:
        account = issuer

    if activity is None:
        activity = 'User Subscriptions'

    kwargs = {'dids': dids, 'copies': copies, 'rse_expression': rse_expression, 'weight': weight, 'lifetime': lifetime,
              'grouping': grouping, 'account': account, 'locked': locked, 'subscription_id': subscription_id,
              'source_replica_expression': source_replica_expression, 'notify': notify, 'activity': activity,
              'purge_replicas': purge_replicas, 'ignore_availability': ignore_availability, 'comment': comment,
              'ask_approval': ask_approval, 'asynchronous': asynchronous, 'delay_injection': delay_injection, 'priority': priority,
              'split_container': split_container, 'meta': meta}

    validate_schema(name='rule', obj=kwargs, vo=vo)

    with db_session(DatabaseOperationType.WRITE) as session:
        auth_result = has_permission(issuer=issuer, vo=vo, action='add_rule', kwargs=kwargs, session=session)
        if not auth_result.allowed:
            raise AccessDenied('Account %s can not add replication rule. %s' % (issuer, auth_result.message))

        account_internal = InternalAccount(account, vo=vo)
        dids_with_internal_scope = [{'name': d['name'], 'scope': InternalScope(d['scope'], vo=vo)} for d in dids]

        return rule.add_rule(account=account_internal,
                             dids=dids_with_internal_scope,
                             copies=copies,
                             rse_expression=rse_expression,
                             grouping=grouping,
                             weight=weight,
                             lifetime=lifetime,
                             locked=locked,
                             subscription_id=subscription_id,
                             source_replica_expression=source_replica_expression,
                             activity=activity,
                             notify=notify,
                             purge_replicas=purge_replicas,
                             ignore_availability=ignore_availability,
                             comment=comment,
                             ask_approval=ask_approval,
                             asynchronous=asynchronous,
                             delay_injection=delay_injection,
                             priority=priority,
                             split_container=split_container,
                             meta=meta,
                             session=session)


def get_replication_rule(rule_id: str, issuer: str, vo: str = DEFAULT_VO) -> dict[str, Any]:
    """
    Get replication rule by it's id.

    :param rule_id: The rule_id to get.
    :param issuer: The issuing account of this operation.
    :param vo: The VO of the issuer.
    """
    kwargs = {'rule_id': rule_id}
    with db_session(DatabaseOperationType.READ) as session:
        if is_multi_vo(session=session):
            auth_result = has_permission(issuer=issuer, vo=vo, action='access_rule_vo', kwargs=kwargs, session=session)
            if not auth_result.allowed:
                raise AccessDenied('Account %s can not access rules at other VOs. %s' % (issuer, auth_result.message))
        result = rule.get_rule(rule_id, session=session)
        return gateway_update_return_dict(result, session=session)


def list_replication_rules(
    filters: Optional[dict[str, Any]] = None,
    vo: str = DEFAULT_VO,
) -> "Iterator[dict[str, Any]]":
    """
    Lists replication rules based on a filter.

    :param filters: dictionary of attributes by which the results should be filtered.
    :param vo: The VO to act on.
    """
    # If filters is empty, create a new dict to avoid overwriting the function's default
    filters = filters or {}

    if 'scope' in filters:
        scope = filters['scope']
    else:
        scope = '*'
    filters['scope'] = InternalScope(scope=scope, vo=vo)

    if 'account' in filters:
        account = filters['account']
    else:
        account = '*'
    filters['account'] = InternalAccount(account=account, vo=vo)

    with db_session(DatabaseOperationType.READ) as session:
        rules = rule.list_rules(filters, session=session)
        for r in rules:
            yield gateway_update_return_dict(r, session=session)


def list_replication_rule_history(
    rule_id: str,
    issuer: str,
    vo: str = DEFAULT_VO,
) -> "Iterator[dict[str, Any]]":
    """
    Lists replication rule history..

    :param rule_id: The rule_id to list.
    :param issuer: The issuing account of this operation.
    :param vo: The VO of the issuer.
    """
    kwargs = {'rule_id': rule_id}
    with db_session(DatabaseOperationType.READ) as session:
        if is_multi_vo(session=session):
            auth_result = has_permission(issuer=issuer, vo=vo, action='access_rule_vo', kwargs=kwargs, session=session)
            if not auth_result.allowed:
                raise AccessDenied('Account %s can not access rules at other VOs. %s' % (issuer, auth_result.message))
        return rule.list_rule_history(rule_id, session=session)


def list_replication_rule_full_history(
    scope: str,
    name: str,
    vo: str = DEFAULT_VO,
) -> "Iterator[dict[str, Any]]":
    """
    List the rule history of a DID.

    :param scope: The scope of the DID.
    :param name: The name of the DID.
    :param vo: The VO to act on.
    """
    scope_internal = InternalScope(scope, vo=vo)
    with db_session(DatabaseOperationType.READ) as session:
        rules = rule.list_rule_full_history(scope_internal, name, session=session)
        for r in rules:
            yield gateway_update_return_dict(r, session=session)


def list_associated_replication_rules_for_file(
    scope: str,
    name: str,
    vo: str = DEFAULT_VO,
) -> "Iterator[dict[str, Any]]":
    """
    Lists associated replication rules by file.

    :param scope: Scope of the file..
    :param name:  Name of the file.
    :param vo: The VO to act on.
    """
    scope_internal = InternalScope(scope, vo=vo)
    with db_session(DatabaseOperationType.READ) as session:
        rules = rule.list_associated_rules_for_file(scope=scope_internal, name=name, session=session)
        for r in rules:
            yield gateway_update_return_dict(r, session=session)


def delete_replication_rule(
    rule_id: str,
    purge_replicas: Optional[bool],
    issuer: str,
    vo: str = DEFAULT_VO,
) -> None:
    """
    Deletes a replication rule and all associated locks.

    :param rule_id:        The id of the rule to be deleted
    :param purge_replicas: Purge the replicas immediately
    :param issuer:         The issuing account of this operation
    :param vo:             The VO to act on.
    :raises:               RuleNotFound, AccessDenied
    """
    kwargs = {'rule_id': rule_id, 'purge_replicas': purge_replicas}
    with db_session(DatabaseOperationType.WRITE) as session:
        if is_multi_vo(session=session):
            auth_result = has_permission(issuer=issuer, vo=vo, action='access_rule_vo', kwargs=kwargs, session=session)
            if not auth_result.allowed:
                raise AccessDenied('Account %s can not access rules at other VOs. %s' % (issuer, auth_result.message))
        auth_result = has_permission(issuer=issuer, vo=vo, action='del_rule', kwargs=kwargs)
        if not auth_result.allowed:
            raise AccessDenied('Account %s can not remove this replication rule. %s' % (issuer, auth_result.message))
        rule.delete_rule(rule_id=rule_id, purge_replicas=purge_replicas, soft=True, session=session)


def update_replication_rule(
    rule_id: str,
    options: dict[str, Any],
    issuer: str,
    vo: str = DEFAULT_VO,
) -> None:
    """
    Update lock state of a replication rule.

    :param rule_id:     The rule_id to lock.
    :param options:     Options dictionary.
    :param issuer:      The issuing account of this operation
    :param vo:          The VO to act on.
    :raises:            RuleNotFound if no Rule can be found.
    """
    kwargs = {'rule_id': rule_id, 'options': options}
    with db_session(DatabaseOperationType.WRITE) as session:
        if is_multi_vo(session=session):
            auth_result = has_permission(issuer=issuer, vo=vo, action='access_rule_vo', kwargs=kwargs, session=session)
            if not auth_result.allowed:
                raise AccessDenied('Account %s can not access rules at other VOs. %s' % (issuer, auth_result.message))
        if 'approve' in options:
            auth_result = has_permission(issuer=issuer, vo=vo, action='approve_rule', kwargs=kwargs, session=session)
            if not auth_result.allowed:
                raise AccessDenied('Account %s can not approve/deny this replication rule. %s' % (issuer, auth_result.message))

            issuer_ia = InternalAccount(issuer, vo=vo)
            if options['approve']:
                rule.approve_rule(rule_id=rule_id, approver=issuer_ia, session=session)
            else:
                rule.deny_rule(rule_id=rule_id, approver=issuer_ia, reason=options.get('comment', None), session=session)
        else:
            auth_result = has_permission(issuer=issuer, vo=vo, action='update_rule', kwargs=kwargs, session=session)
            if not auth_result.allowed:
                raise AccessDenied('Account %s can not update this replication rule. %s' % (issuer, auth_result.message))
            if 'account' in options:
                options['account'] = InternalAccount(options['account'], vo=vo)
            rule.update_rule(rule_id=rule_id, options=options, session=session)


def reduce_replication_rule(
    rule_id: str,
    copies: int,
    exclude_expression: Optional[str],
    issuer: str,
    vo: str = DEFAULT_VO,
) -> str:
    """
    Reduce the number of copies for a rule by atomically replacing the rule.

    :param rule_id:             Rule to be reduced.
    :param copies:              Number of copies of the new rule.
    :param exclude_expression:  RSE Expression of RSEs to exclude.
    :param issuer:              The issuing account of this operation
    :param vo:                  The VO to act on.
    :raises:                    RuleReplaceFailed, RuleNotFound
    """
    kwargs = {'rule_id': rule_id, 'copies': copies, 'exclude_expression': exclude_expression}
    with db_session(DatabaseOperationType.WRITE) as session:
        if is_multi_vo(session=session):
            auth_result = has_permission(issuer=issuer, vo=vo, action='access_rule_vo', kwargs=kwargs, session=session)
            if not auth_result.allowed:
                raise AccessDenied('Account %s can not access rules at other VOs. %s' % (issuer, auth_result.message))
        auth_result = has_permission(issuer=issuer, vo=vo, action='reduce_rule', kwargs=kwargs, session=session)
        if not auth_result.allowed:
            raise AccessDenied('Account %s can not reduce this replication rule. %s' % (issuer, auth_result.message))

        return rule.reduce_rule(rule_id=rule_id, copies=copies, exclude_expression=exclude_expression, session=session)


def examine_replication_rule(
    rule_id: str,
    issuer: str,
    vo: str = DEFAULT_VO,
) -> dict[str, Any]:
    """
    Examine a replication rule.

    :param rule_id: The rule_id to get.
    :param issuer: The issuing account of this operation.
    :param vo: The VO of the issuer.
    """
    kwargs = {'rule_id': rule_id}
    with db_session(DatabaseOperationType.READ) as session:
        if is_multi_vo(session=session):
            auth_result = has_permission(issuer=issuer, vo=vo, action='access_rule_vo', kwargs=kwargs, session=session)
            if not auth_result.allowed:
                raise AccessDenied('Account %s can not access rules at other VOs. %s' % (issuer, auth_result.message))
        result = rule.examine_rule(rule_id, session=session)
        result = gateway_update_return_dict(result, session=session)
        if 'transfers' in result:
            result['transfers'] = [gateway_update_return_dict(t, session=session) for t in result['transfers']]
    return result


def move_replication_rule(
    rule_id: str,
    rse_expression: str,
    override: dict[str, Any],
    issuer: str,
    vo: str = DEFAULT_VO,
) -> str:
    """
    Move a replication rule to another RSE and, once done, delete the original one.

    :param rule_id:                    Rule to be moved.
    :param rse_expression:             RSE expression of the new rule.
    :param override:                   Configurations to update for the new rule.
    :param vo:                         The VO to act on.
    :raises:                           RuleNotFound, RuleReplaceFailed, InvalidRSEExpression, AccessDenied
    """
    override = override.copy()
    if 'account' in override:
        override['account'] = InternalAccount(override['account'], vo=vo)
    kwargs = {
        'rule_id': rule_id,
        'rse_expression': rse_expression,
        'override': override,
    }

    with db_session(DatabaseOperationType.WRITE) as session:
        if is_multi_vo(session=session):
            auth_result = has_permission(issuer=issuer, vo=vo, action='access_rule_vo', kwargs=kwargs, session=session)
            if not auth_result.allowed:
                raise AccessDenied('Account %s can not access rules at other VOs. %s' % (issuer, auth_result.message))
        auth_result = has_permission(issuer=issuer, vo=vo, action='move_rule', kwargs=kwargs, session=session)
        if not auth_result.allowed:
            raise AccessDenied('Account %s can not move this replication rule. %s' % (issuer, auth_result.message))

        return rule.move_rule(**kwargs, session=session)
