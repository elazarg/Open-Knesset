import json

from django import template
from agendas.models import Agenda, AgendaVote, AgendaMeeting, AgendaBill, UserSuggestedVote
from agendas.forms import VoteLinkingFormSet, MeetingLinkingFormSet

#from django.core.cache import cache
from django.core.exceptions import ObjectDoesNotExist

register = template.Library()

@register.inclusion_tag('agendas/agendasfor.html')
def agendas_for(user, obj, object_type):
    ''' renders the relevent agenda for the object obj and a form for the
        agendas the given user can edit
    '''
    meaning = {'vote':              ('vote',    AgendaVote,     VoteLinkingFormSet),
               'committeemeeting':  ('meeting', AgendaMeeting,  MeetingLinkingFormSet),
               'bill':              ('bill',    AgendaBill,     VoteLinkingFormSet)
                }
    m = meaning[object_type]
    d = { m[0]:obj }
    authenticated = user.is_authenticated()
    
    def get_r(a):
        r = {'agenda_name': a.name, 'agenda_id': a.id,
             'obj_id': obj.id, 'object_type':object_type}
        try:
            av = getattr(a, 'agenda{}s'.format(m[0])).get(**d)
            if not av:
                raise ObjectDoesNotExist()
        except ObjectDoesNotExist:
            r['weight'] = None
            r['reasoning'] = u''
        else: 
            r['weight'] = av.score
            r['reasoning'] = av.reasoning
            try:
                r['importance'] = av.importance
            except AttributeError:
                pass
        return r
    
    formset = m[2](initial = [get_r(a) for a in user.agendas.all()]) if authenticated else None
    
    suggested_agendas = None
    suggest_agendas = None
    av = m[1].objects.filter(agenda__in=Agenda.objects.get_relevant_for_user(user), **d).distinct()
    if object_type=='vote':
        suggest_agendas = Agenda.objects.get_possible_to_suggest(user=user, **d)
        if authenticated:
            suggested_agendas = UserSuggestedVote.objects.filter(user=user, **d)

    return {'formset': formset,
            'agendas': av,
            'object_type': object_type,
            'suggest_agendas': suggest_agendas,
            'suggested_agendas': suggested_agendas,
            'suggest_agendas_login': suggest_agendas == False,
            'url': obj.get_absolute_url(),
           }

@register.inclusion_tag('agendas/agenda_list_item.html')
def agenda_list_item(agenda, watched_agendas=None, agenda_votes_num=None, agenda_party_values=None,
                                         parties_lookup=None, editors_lookup=None, editor_ids=None):
    #cached_context = cache.get('agenda_parties_%d' % agenda.id)
    #if not cached_context:
    #    selected_parties = agenda.selected_instances(Party, top=20,bottom=0)['top']
    #    cached_context = {'selected_parties': selected_parties }
    #    cache.set('agenda_parties_%d' % agenda.id, cached_context, 900)
    party_scores = [(parties_lookup.get(val[0]), val[1]) for val in agenda_party_values]
    enum = list(enumerate(party_scores))
    enumerated_party = [(idx+0.5, values[0]) for idx, values in enum]
    enumerated_score = [(idx, values[1]) for idx, values in enum]
    return {'agenda': agenda,
            'watched_agendas': watched_agendas,
            'party_scores': json.dumps(enumerated_score, ensure_ascii=False),
            'party_list': json.dumps(enumerated_party, ensure_ascii=False),
            'agenda_votes_num': agenda_votes_num,
            'editors': editors_lookup,
            'editor_ids': editor_ids}