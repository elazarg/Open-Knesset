import logging
from operator import itemgetter
from itertools import chain

from django.utils.translation import ugettext_lazy as _
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.template import RequestContext
from django.db.models import Count
from django.http import HttpResponseRedirect, HttpResponseNotAllowed, HttpResponseForbidden
from django.shortcuts import get_object_or_404, render_to_response
from django.core.urlresolvers import reverse
from django.core.cache import cache
from django.views.decorators.csrf import ensure_csrf_cookie
from django.utils.decorators import method_decorator

from hashnav import DetailView, ListView
#from laws.models import Vote
from mks.models import Member, Party
from apis.urls import vote_handler

from forms import (EditAgendaForm, AddAgendaForm, VoteLinkingFormSet,
                   MeetingLinkingFormSet)
from models import Agenda, AgendaVote, AgendaMeeting, AgendaBill

import queries

from django.test import Client
from django.core.handlers.wsgi import WSGIRequest
from auxiliary.views import GetMoreView


logger = logging.getLogger("open-knesset.agendas.views")


class AgendaListView(ListView):

    def get_queryset(self):
        if not self.request.user.is_authenticated():
            return Agenda.objects.get_relevant_for_user(user=None)
        else:
            return Agenda.objects.get_relevant_for_user(user=self.request.user)

    def get_context(self, *args, **kwargs):
        context = super(AgendaListView, self).get_context(*args, **kwargs)
        # optimization - create query for votes per agenda
        # store in context as dictionary votes[agendaid]=<votenum>
        agenda_votes_results = Agenda.objects.values("id").annotate(Count("votes"))
        agenda_votes = {vote["id"]:str(vote["votes__count"]) for vote in agenda_votes_results}
        parties_lookup = {party.id: party.name for party in Party.current_knesset.all()}

        allAgendaPartyVotes = cache.get('AllAgendaPartyVotes')
        if not allAgendaPartyVotes:
            # filtering for current knesset is done here

            allAgendaPartyVotes = queries.getAllAgendaPartyVotes()

            for agenda_id, party_votes in allAgendaPartyVotes.iteritems():
                allAgendaPartyVotes[agenda_id] = [
                    (pid, name) for pid, name in party_votes if pid in parties_lookup]

            cache.set('AllAgendaPartyVotes', allAgendaPartyVotes, 1800)

        #so should `watched` be False or None?
        watched = self.request.user.get_profile().agendas if self.request.user.is_authenticated() else None
        
        agendaEditorIds = queries.getAgendaEditorIds()
        allEditorIds = list(set(chain.from_iterable(agendaEditorIds.values())))
        editors = User.objects.filter(id__in=allEditorIds)
        context['agenda_editors'] = agendaEditorIds
        context['editors'] = {obj.id:obj for obj in  editors}
        context['watched'] = watched
        context['agenda_votes'] = agenda_votes
        context['agenda_party_values'] = allAgendaPartyVotes
        context['parties_lookup'] = parties_lookup
        return context


class AgendaDetailView(DetailView):

    model = Agenda

    INITIAL = 4

    class ForbiddenAgenda(Exception):
        pass

    @method_decorator(ensure_csrf_cookie)
    def dispatch(self, *args, **kwargs):
        return super(AgendaDetailView, self).dispatch(*args, **kwargs)

    def get(self, request, *arg, **kwargs):
        try:
            response = super(AgendaDetailView, self).get(request, *arg, **kwargs)
        except self.ForbiddenAgenda:
            return HttpResponseForbidden()
        return response

    def get_object(self):
        obj = super(AgendaDetailView, self).get_object()
        has_id = Agenda.objects.get_relevant_for_user(user=self.request.user).filter(pk=obj.id).count() > 0
        if has_id:
            return obj
        else:
            raise self.ForbiddenAgenda

    def get_context_data(self, *args, **kwargs):
        context = super(AgendaDetailView, self).get_context_data(*args, **kwargs)
        agenda = context['object']
        try:
            context['title'] = "%s" % agenda.name
        except AttributeError:
            context['title'] = _('None')

        if self.request.user.is_authenticated():
            p = self.request.user.get_profile()
            watched = agenda in p.agendas
            watched_members = p.members
        else:
            watched = False
            watched_members = False
        context.update({'watched_object': watched})
        context['watched_members'] = watched_members

        mks_values = agenda.get_mks_values()
        context['agenda_mk_values'] = dict(mks_values)
        #cmp_rank = lambda x, y: x[1]['rank'] - y[1]['rank']
        def get_first(iterable):
            return [x[0] for x in iterable]
        
        if 'all_mks' in self.request.GET.keys():
            context['all_mks_ids'] = get_first(mks_values[:200])
            context['all_mks'] = True
        else:
            context['mks_top'] = get_first(mks_values[:5])
            context['mks_bottom'] = get_first(mks_values[-5:])

        allAgendaPartyVotes = agenda.get_all_party_values()
        context['agenda_party_values'] = { k:v for k, v in allAgendaPartyVotes.setdefault(agenda.id, [])}
        context['agendaTopParties'] = get_first(sorted(allAgendaPartyVotes[agenda.id], key=itemgetter(1), reverse=True)[:20])
        
        agenda_votes_name = 'agenda_votes_{}'.format(agenda.id)
        agenda_votes = cache.get(agenda_votes_name)

        if not agenda_votes:
            agenda_votes = agenda.agendavotes.order_by('-vote__time').select_related('vote')
            cache.set(agenda_votes_name, agenda_votes, 900)

        try:
            total_votes = agenda_votes.count()
        except TypeError:
            total_votes = len(agenda_votes)

        context['INITIAL'] = self.INITIAL
        context['agenda_votes_more'] = total_votes > self.INITIAL
        context['agenda_votes'] = agenda_votes[:self.INITIAL]

        agenda_bills = agenda.agendabills.all()
        context['agenda_bills_more'] = agenda_bills.count() > self.INITIAL
        context['agenda_bills'] = agenda_bills[:self.INITIAL]

        agenda_meetings = agenda.agendameetings.all()
        context['agenda_meetings_more'] = agenda_meetings.count() > self.INITIAL
        context['agenda_meetings'] = agenda_meetings[:self.INITIAL]

        # Optimization: get all parties and members before rendering
        # Further possible optimization: only bring parties/members needed for rendering
        for name, cls in [('parties', Party), ('members', Member)]:
            context[name] = { party.id:party for party in cls.objects.all() }
        return context


class AgendaVotesMoreView(GetMoreView):

    paginate_by = 10
    template_name = 'agendas/agenda_vote_partial.html'

    def get_queryset(self):
        agenda = get_object_or_404(Agenda, pk=self.kwargs['pk'])
        agenda_name = 'agenda_votes_{}'.format(agenda.id)
        agenda_votes = cache.get(agenda_name)

        if not agenda_votes:
            agenda_votes = agenda.agendavotes.order_by('-vote__time').select_related('vote')
            cache.set(agenda_name, agenda_votes, 900)
        return agenda_votes

    def get_context_data(self, *args, **kwargs):
        ctx = super(AgendaVotesMoreView, self).get_context_data(*args, **kwargs)
        ctx['watched_members'] = self.request.user.get_profile().members if self.request.user.is_authenticated() else False
        return ctx


class AgendaBillsMoreView(GetMoreView):

    paginate_by = 10
    template_name = 'agendas/agenda_bill_partial.html'

    def get_queryset(self):
        agenda = get_object_or_404(Agenda, pk=self.kwargs['pk'])
        return agenda.agendabills.all()


class AgendaMeetingsMoreView(GetMoreView):

    paginate_by = 10
    template_name = 'agendas/agenda_meeting_partial.html'

    def get_queryset(self):
        agenda = get_object_or_404(Agenda, pk=self.kwargs['pk'])
        return agenda.agendameetings.all()


class AgendaVoteDetailView (DetailView):
    model = AgendaVote
    template_name = 'agendas/agenda_vote_detail.html'

    def get_context_data(self, *args, **kwargs):
        context = super(AgendaVoteDetailView, self).get_context_data(*args, **kwargs)
        agendavote = context['object']
        vote = agendavote.vote
        agenda = agendavote.agenda
        try:
            context['title'] = _("Comments on agenda %(agenda)s vote %(vote)s") % {
                  'vote':vote.title,
                  'agenda':agenda.name}
        except AttributeError:
            context['title'] = _('None')
            logger.error('Attribute error trying to generate title for agenda %d vote %d' % (agenda.id, vote.id))
        return context

class AgendaMeetingDetailView (DetailView):
    model = AgendaMeeting
    template_name = 'agendas/agenda_meeting_detail.html'

    def get_context_data(self, *args, **kwargs):
        context = super(AgendaMeetingDetailView , self).get_context_data(*args, **kwargs)
        agendameeting = context['object']
        meeting = agendameeting.meeting
        agenda = agendameeting.agenda
        try:
            context['title'] = _("Comments on agenda %(agenda)s meeting %(meeting)s") % {
                  'meeting':meeting,
                  'agenda':agenda.name}
        except AttributeError:
            context['title'] = _('None')
            logger.error('Attribute error trying to generate title for agenda %d meeting %d' % (agenda.id, meeting.id))
        return context

class AgendaBillDetailView (DetailView):
    model = AgendaBill
    template_name = 'agendas/agenda_bill_detail.html'

    def get_context_data(self, *args, **kwargs):
        context = super(AgendaBillDetailView , self).get_context_data(*args, **kwargs)
        agendabill = context['object']
        bill = agendabill.bill
        agenda = agendabill.agenda
        try:
            context['title'] = _("Comments on agenda %(agenda)s bill %(bill)s") % {
                  'bill':bill.full_title,
                  'agenda':agenda.name}
        except AttributeError:
            context['title'] = _('None')
            logger.error('Attribute error trying to generate title for agenda %d bill %d' % (agenda.id, bill.id))
        return context

class AgendaMkDetailView (DetailView):
    model = Agenda
    template_name = 'agendas/mk_agenda_detail.html'

    def get_context_data(self, *args, **kwargs):
        context = super(AgendaMkDetailView, self).get_context_data(*args, **kwargs)
        agenda = context['object']
        context['agenda_url'] = agenda.get_absolute_url()
        context['agenda_name'] = agenda.name
        member = Member.objects.get(pk=context['member_id'])
        context['member'] = member
        context['member_url'] = member.get_absolute_url()
        context['score'] = agenda.member_score(member)

        try:
            context['title'] = _("Analysis of %(member)s votes by agenda %(agenda)s") % {'member':member.name, 'agenda':agenda.name}
        except AttributeError:
            context['title'] = _('None')
            logger.error('Attribute error trying to generate title for agenda %d member %d' % (self.object_id, self.member_id))

        related_mk_votes = agenda.related_mk_votes(member)

        if self.request.user.is_authenticated():
            p = self.request.user.get_profile()
            watched = agenda in p.agendas
        else:
            watched = False

        context.update({'watched_object': watched})
        context.update({'related_votes': related_mk_votes})

        return context

class AgendaDetailEditView (DetailView):
    model = Agenda
    template_name = 'agendas/agenda_detail_edit.html'

    def get(self, request, *args, **kwargs):
        object_id = kwargs.get('pk' , kwargs.get('object_id', None))
        agenda = get_object_or_404(Agenda, pk=object_id)
        if request.user in agenda.editors.all():
            return super(AgendaDetailEditView, self).get(request, *args, **kwargs)
        else:
            return HttpResponseRedirect(agenda.get_absolute_url())

    def get_context_data(self, *args, **kwargs):
        context = super(AgendaDetailEditView, self).get_context_data(*args, **kwargs)
        agenda = context['object']
        form = getattr (self, 'form', None)
        if form is None:
            form = EditAgendaForm(agenda=agenda if self.request.method == 'GET' else None)
        context['form'] = form
        return context

    def post(self, request, *args, **kwargs):
        object_id = kwargs.get('pk' , kwargs.get('object_id', None))
        agenda = get_object_or_404(Agenda, pk=object_id)
        if request.user not in agenda.editors.all():
            return HttpResponseForbidden()
        form = EditAgendaForm(data=self.request.POST)
        if form.is_valid():  # All validation rules pass
            agenda.name = form.cleaned_data['name']
            agenda.public_owner_name = form.cleaned_data['public_owner_name']
            agenda.description = form.cleaned_data['description']
            agenda.save()
#            return HttpResponseRedirect(reverse('agenda-detail',kwargs={'object_id':agenda.id}))
            return HttpResponseRedirect(agenda.get_absolute_url())
        else:
            self.form = form
            return super(AgendaDetailEditView, self).get(request, *args, **kwargs)

class MockApiCaller(Client):
    def get_vote_api(self, vote):
        return vote_handler(self.get('/api/vote/{}/'.format(vote.id)))  # TODO: get the url from somewhere else?

    def request(self, **request):
        environ = {
            'HTTP_COOKIE': self.cookies,
            'PATH_INFO': '/',
            'QUERY_STRING': '',
            'REQUEST_METHOD': 'GET',
            'SCRIPT_NAME': '',
            'SERVER_NAME': 'testserver',
            'SERVER_PORT': 80,
            'SERVER_PROTOCOL': 'HTTP/1.1',
        }
        environ.update(self.defaults)
        environ.update(request)
        return WSGIRequest(environ)

mock_api = MockApiCaller()

@login_required
def agenda_add_view(request):
    #allowed_methods = ['GET', 'POST']
    template_name = 'agendas/agenda_add.html'

    if not request.user.is_superuser:
        return HttpResponseRedirect('/agenda/')

    if request.method == 'POST':
        form = AddAgendaForm(request.POST)
        if form.is_valid():
            agenda = Agenda()
            agenda.name = form.cleaned_data['name']
            agenda.public_owner_name = form.cleaned_data['public_owner_name']
            agenda.description = form.cleaned_data['description']
            agenda.save()
            agenda.editors.add(request.user)
            return HttpResponseRedirect(agenda.get_absolute_url())  # Redirect after POST
    else:
        initial_data = {'public_owner_name': request.user.username}
        form = AddAgendaForm(initial=initial_data)  # An unbound form with initial data

    return render_to_response(template_name, {'form': form}, context_instance=RequestContext(request))


# used for redirection after an object has been added to the agenda
object_redirect = {'vote':('vote-detail', 'vote-list'),
                   'bill':('bill-detail', 'bill-list'),
                   'committeemeeting':('committee-meeting', 'committee-list'),
                  }
object_formset_classes = {'vote':VoteLinkingFormSet,
                          'bill':VoteLinkingFormSet,
                          'committeemeeting':MeetingLinkingFormSet,
                         }

@login_required
def update_editors_agendas(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])
    object_type = request.POST.get('form-0-object_type', None)
    object_id = request.POST.get('form-0-obj_id', None)
    vl_formset = object_formset_classes[object_type](request.POST)
    if not vl_formset.is_valid():
        # TODO: Error handling: what to do with illeal forms?
        logger.info("invalid formset")
        logger.info("{}".format(vl_formset.errors))
    else:
        for a in vl_formset.cleaned_data:
            if a:
                # Check that the user is an editor of the agenda
                # he's trying to edit
                try:
                    agenda = Agenda.objects.get(pk=a['agenda_id'])
                    if request.user not in agenda.editors.all():
                        return HttpResponseForbidden()
                except Agenda.DoesNotExist:
                    return HttpResponseForbidden()

                if a['object_type'] == 'vote':
                    if a['DELETE']:
                        try:
                            object_id = a['obj_id']
                            av = AgendaVote.objects.get(
                                   agenda__id=a['agenda_id'],
                                   vote__id=a['obj_id'])
                            av.delete()
                        except AgendaVote.DoesNotExist:
                            pass
                    else:  # not delete, so try to create
                        if (a['weight'] is not '' and
                            a['importance'] is not ''):
                            try:
                                object_id = a['obj_id']
                                av = AgendaVote.objects.get(
                                       agenda__id=a['agenda_id'],
                                       vote__id=a['obj_id'])
                                av.score = a['weight']
                                av.importance = a['importance']
                                av.reasoning = a['reasoning']
                                av.save()
                            except AgendaVote.DoesNotExist:
                                av = AgendaVote(
                                       agenda_id=int(a['agenda_id']),
                                       vote_id=int(a['obj_id']),
                                       score=a['weight'],
                                       importance=a['importance'],
                                       reasoning=a['reasoning'])
                                av.save()
                if a['object_type'] == 'bill':
                    if a['DELETE']:
                        try:
                            object_id = a['obj_id']
                            av = AgendaBill.objects.get(
                                   agenda__id=a['agenda_id'],
                                   bill__id=a['obj_id'])
                            av.delete()
                        except AgendaBill.DoesNotExist:
                            pass
                    else:  # not delete, so try to create
                        if (a['weight'] is not '' and
                            a['importance'] is not ''):
                            try:
                                object_id = a['obj_id']
                                av = AgendaBill.objects.get(
                                       agenda__id=a['agenda_id'],
                                       bill__id=a['obj_id'])
                                av.score = a['weight']
                                av.importance = a['importance']
                                av.reasoning = a['reasoning']
                                av.save()
                            except AgendaBill.DoesNotExist:
                                av = AgendaBill(
                                       agenda_id=int(a['agenda_id']),
                                       bill_id=int(a['obj_id']),
                                       score=a['weight'],
                                       importance=a['importance'],
                                       reasoning=a['reasoning'])
                                av.save()
                if a['object_type'] == 'committeemeeting':
                    if a['DELETE']:
                        try:
                            object_id = a['obj_id']
                            av = AgendaMeeting.objects.get(
                                   agenda__id=a['agenda_id'],
                                   meeting__id=a['obj_id'])
                            av.delete()
                        except AgendaMeeting.DoesNotExist:
                            pass
                    else:  # not delete, so try to create
                        try:
                            object_id = a['obj_id']
                            av = AgendaMeeting.objects.get(
                                   agenda__id=a['agenda_id'],
                                   meeting__id=a['obj_id'])
                            av.score = a['weight']
                            av.reasoning = a['reasoning']
                            av.save()
                        except AgendaMeeting.DoesNotExist:
                            av = AgendaMeeting(
                                   agenda_id=int(a['agenda_id']),
                                   meeting_id=int(a['obj_id']),
                                   score=a['weight'],
                                   reasoning=a['reasoning'])
                            av.save()
            else:
                logger.info("invalid form")

    if object_type in object_redirect:
        if object_id:  # return to object page
            return HttpResponseRedirect(
                    reverse(object_redirect[object_type][0],
                            kwargs={'pk':object_id}))
        else:  # return to list
            return HttpResponseRedirect(reverse(object_redirect[object_type][1]))
    else:
        logger.warn('unknown object_type')
        return HttpResponseRedirect(reverse('main'))

