'''
API for the agendas app
'''
from django.utils.timezone import datetime

import tastypie.fields as fields
from avatar.templatetags.avatar_tags import avatar_url
from django.contrib.auth.models import User

from models import Agenda, AgendaVote
from apis.resources.base import BaseResource
from mks.models import Member, Party

class UserResource(BaseResource):
    class Meta(BaseResource.Meta):
        queryset = User.objects.all()
        include_absolute_url = True
        include_resource_uri = False
        allowed_methods = ['get']
        fields = ['username']

    avatar = fields.CharField()

    def dehydrate_avatar(self, bundle):
        return avatar_url(bundle.obj, 48)


class AgendaVoteResource(BaseResource):
    class Meta(BaseResource.Meta):
        queryset = AgendaVote.objects.select_related()
        allowed_methods = ['get']

    title = fields.CharField()

    def dehydrate_title(self, bundle):
        return bundle.obj.vote.title


class AgendaTodoResource(BaseResource):
    class Meta(BaseResource.Meta):
        allowed_methods = ['get']
        queryset = Agenda.objects.all()
        resource_name = 'agenda-todo'
        fields = ['votes_by_conrtoversy', 'votes_by_agendas']

    votes_by_controversy = fields.ListField()
    votes_by_agendas = fields.ListField()

    # TODO: Make this a parameter or setting or something
    NUM_SUGGESTIONS = 10

    def dehydrate_votes_by_agendas(self, bundle):
        votes = bundle.obj.get_suggested_votes_by_agendas(
            AgendaTodoResource.NUM_SUGGESTIONS)
        return self._dehydrate_votes(votes)

    def dehydrate_votes_by_controversy(self, bundle):
        votes = bundle.obj.get_suggested_votes_by_controversy(
            AgendaTodoResource.NUM_SUGGESTIONS)
        return self._dehydrate_votes(votes)

    def _dehydrate_votes(self, votes):
        return [{'id':vote.id,
                'url':vote.get_absolute_url(),
                'title':vote.title,
                'score':vote.score} for vote in votes]


class AgendaResource(BaseResource):
    ''' Agenda API '''

    members = fields.ListField()
    parties = fields.ListField()
    votes = fields.ListField()
    editors = fields.ListField()
    ranges = fields.ListField()

    class Meta(BaseResource.Meta):
        queryset = Agenda.objects.filter(
            is_public=True).prefetch_related('agendavotes__vote', 'editors')
        allowed_methods = ['get']
        include_absolute_url = True
        excludes = ['is_public']
        list_fields = ['name', 'id', 'description', 'public_owner_name']

    def dehydrate_members(self, bundle):
        rangesString = bundle.request.GET.get('ranges', None)
        ranges = rangesString and [
                    [datetime.strptime(val,"%Y%m") if val else None for val in rangeString.split('-')]
                      for rangeString in  rangesString.split(',')]
        mks_values = dict(bundle.obj.get_mks_values(ranges))
        members = []
        for mk in Member.objects.filter(pk__in=mks_values.keys(),
                                        current_party__isnull=False).select_related('current_party'):
            # TODO: this sucks, performance wise
            current_party = mk.current_party
            mk_data = mks_values[mk.id]
            if not isinstance(mk_data, list):
                mk_data = [mk_data]
            s = list(zip(*[(x['score'], x['rank'], x['volume'], x['numvotes']) for x in mk_data]))
            members.append(dict(
                id=mk.id,
                name=mk.name,
                score=s[0],
                rank=s[1],
                volume=s[2],
                numvotes=s[3],
                absolute_url=mk.get_absolute_url(),
                party=current_party.name,
                party_url=current_party.get_absolute_url(),
                party_id=current_party.pk
            ))

        return members

    def dehydrate_parties(self, bundle):
        party_values = {party_data[0]:{'score':party_data[1],'volume':party_data[2]}
                         for party_data in  bundle.obj.get_party_values()}
        parties = []
        for party in Party.objects.all():
            d = {'name':party.name, 'absolute_url':party.get_absolute_url()}
            try: d.update(party_values[party.pk])
            except KeyError: pass 
            parties.append(d)
        return parties

    def dehydrate_votes(self, bundle):
        return [
            dict(title=v.vote.title, id=v.vote_id, importance=v.importance,
                 score=v.score, reasoning=v.reasoning)
            for v in bundle.obj.agendavotes.select_related()
        ]

    def dehydrate_editors(self, bundle):
        return [
            dict(absolute_url=e.get_absolute_url(), username=e.username,
                 avatar=avatar_url(e, 48))
            for e in bundle.obj.editors.all()
        ]

    def dehydrate_ranges(self, bundle):
        rangesString = bundle.request.GET.get('ranges', '-')
        ranges = [[int(val) if val else None for val in rangeString.split('-')]
                   for rangeString in rangesString.split(',')]
        results = []
        for start, end in ranges:
            rangeResult = {}
            if start:
                rangeResult['from'] = datetime(year=start / 100, month=start % 100, day=1)
            if end:
                rangeResult['to'] = datetime(year=end / 100, month=end % 100, day=1)
            results.append(rangeResult)
        return results
