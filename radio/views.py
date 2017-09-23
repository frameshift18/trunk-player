#import functools
import sys
import re
from itertools import chain
from django.shortcuts import render, get_object_or_404, render_to_response
from django.http import Http404
from django.views.generic import ListView
from django.db.models import Q
from django.views.decorators.csrf import csrf_protect
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseRedirect
from django.template import RequestContext
from django.contrib.auth import authenticate, login
from django.conf import settings
from django.views.generic import ListView, UpdateView
from django.views.generic.detail import DetailView
from django.contrib.auth.mixins import PermissionRequiredMixin
from django.core.exceptions import ImproperlyConfigured
from .models import *
from rest_framework import viewsets, generics
from .serializers import TransmissionSerializer, TalkGroupSerializer, ScanListSerializer, MenuScanListSerializer, MenuTalkGroupListSerializer
from datetime import datetime, timedelta
from django.utils import timezone
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ObjectDoesNotExist


import pinax.stripe.actions as stripe_actions
import pinax.stripe.models as stripe_models
import stripe
from allauth.account.models import EmailAddress as allauth_emailaddress
from pprint import pprint
from django.contrib import messages
import logging

from .forms import *

logger = logging.getLogger(__name__)


def check_anonymous(decorator):
    """
    Decarator used to see if we allow anonymous access
    """
    anonymous = getattr(settings, 'ALLOW_ANONYMOUS', True)
    return decorator if not anonymous else lambda x: x


def TransDetailView(request, slug):
    template = 'radio/transmission_detail.html'
    status = 'Good'
    try:
        query_data = Transmission.objects.filter(slug=slug)
        if not query_data:
            raise Http404
    except Transmission.DoesNotExist:
        raise Http404
    query_data2 = limit_transmission_history(request, query_data)
    if not query_data2:
        query_data[0].audio_file = None
        status = 'Expired'
    restricted, new_query = restrict_talkgroups(request, query_data)
    if not new_query:
        raise Http404
    return render(request, template, {'object': query_data[0], 'status': status})


class TransmissionViewSet(viewsets.ModelViewSet):
    """
    API endpoint that allows users to be viewed or edited.
    """
    queryset = Transmission.objects.none()
    serializer_class = TransmissionSerializer


class ScanListViewSet(viewsets.ModelViewSet):
    queryset = ScanList.objects.all().prefetch_related('talkgroups')
    serializer_class = ScanListSerializer


class TalkGroupViewSet(viewsets.ModelViewSet):
    """
    API endpoint that allows groups to be viewed or edited.
    """
#    queryset = TalkGroup.objects.filter(public=True)
    serializer_class = TalkGroupSerializer
    base_name = 'TalkGroup'

    def get_queryset(self):
        if settings.ACCESS_TG_RESTRICT:
            tg = allowed_tg_list(self.request.user)
        else:
            tg = TalkGroup.objects.filter(public=True)
        return tg



class TransmissionView(ListView):
    model = Transmission
    paginate_by = 50


def ScanListFilter(request, filter_val):
    template = 'radio/transmission.html'
    return render_to_response(template, {'filter_data': filter_val, 'api_url': '/api_v1/ScanList'})


def TalkGroupFilterNew(request, filter_val):
    template = 'radio/transmission_play.html'
    return render_to_response(template, {'filter_data': filter_val})


def TalkGroupFilterjq(request, filter_val):
    template = 'radio/transmission_list_jq.html'
    return TalkGroupFilterBase(request, filter_val, template)


def TalkGroupFilter(request, filter_val):
    template = 'radio/transmission_list.html'
    return TalkGroupFilterBase(request, filter_val, template)

# Open to anyone
def Generic(request, page_name):
    template = 'radio/generic.html'
    query_data = WebHtml.objects.get(name=page_name)
    return render(request, template, {'html_object': query_data})

def get_user_profile(user):
    if user.is_authenticated():
        user_profile = Profile.objects.get(user=user)
    else:
        try:
            anon_user = User.objects.get(username='ANONYMOUS_USER')
        except User.DoesNotExist:
            raise ImproperlyConfigured('ANONYMOUS_USER is missing from User table, was "./manage.py migrations" not run?')
        user_profile = Profile.objects.get(user=anon_user)
    return user_profile

def get_history_allow(user):
    user_profile = get_user_profile(user)
    if user_profile:
        history_minutes = user_profile.plan.history
    else:
        history_minutes = settings.ANONYMOUS_TIME
    return history_minutes


def limit_transmission_history(request, query_data):
    history_minutes = get_history_allow(request.user)
    if history_minutes > 0:
        time_threshold = timezone.now() - timedelta(minutes=history_minutes)
        query_data = query_data.filter(start_datetime__gt=time_threshold)
    return query_data


def allowed_tg_list(user):
    user_profile = get_user_profile(user)
    tg_list = None
    for group in user_profile.talkgroup_access.all():
       if tg_list is None:
           tg_list = group.talkgroups.all()
       else:
           tg_list = tg_list | group.talkgroups.all()
    if tg_list:
        tg_list = tg_list.distinct()
    else:
        # Set blank talkgroup queryset
        tg_list = TalkGroup.objects.none()
    return tg_list


def restrict_talkgroups(request, query_data):
    ''' Checks to make sure the user can view
        each of the talkgroups in the query_data
        returns ( was_restricted, new query_data )
    '''
    if not settings.ACCESS_TG_RESTRICT:
        return False, query_data
    tg_list = allowed_tg_list(request.user)
    query_data = query_data.filter(talkgroup_info__in=tg_list)
    return None, query_data
    

def TalkGroupFilterBase(request, filter_val, template):
    try:
        tg = TalkGroup.objects.get(alpha_tag__startswith=filter_val)
    except TalkGroup.DoesNotExist:
        raise Http404
    try:
        query_data = Transmission.objects.filter(talkgroup_info=tg).prefetch_related('units')
        query_data = limit_transmission_history(self.request, rc_data)
        restrict_talkgroups(self.request, rc_data)
    except Transmission.DoesNotExist:
        raise Http404
    return render_to_response(template, {'object_list': query_data, 'filter_data': filter_val})


class ScanViewSet(generics.ListAPIView):
    serializer_class = TransmissionSerializer

    def get_queryset(self):
        scanlist = self.kwargs['filter_val']
        try:
            sl = ScanList.objects.get(slug__iexact=scanlist)
        except ScanList.DoesNotExist:
            if scanlist == 'default':
                tg = TalkGroup.objects.all()
            else:
               print("Scan list does not match")
               raise
        else:
            tg = sl.talkgroups.all()
        rc_data = Transmission.objects.filter(talkgroup_info__in=tg).prefetch_related('units').prefetch_related('talkgroup_info')
        rc_data = limit_transmission_history(self.request, rc_data)
        restricted, rc_data = restrict_talkgroups(self.request, rc_data) 
        return rc_data


class TalkGroupFilterViewSet(generics.ListAPIView):
    serializer_class = TransmissionSerializer

    def get_queryset(self):
        tg_var = self.kwargs['filter_val']
        search_tgs = re.split('[\+]', tg_var)
        q = Q()
        for stg in search_tgs:
            q |= Q(common_name__iexact=stg)
            q |= Q(slug__iexact=stg)
        tg = TalkGroup.objects.filter(q)
        rc_data = Transmission.objects.filter(talkgroup_info__in=tg).prefetch_related('units')
        rc_data = limit_transmission_history(self.request, rc_data)
        restricted, rc_data = restrict_talkgroups(self.request, rc_data)
        return rc_data


class UnitFilterViewSet(generics.ListAPIView):
    serializer_class = TransmissionSerializer

    def get_queryset(self):
        unit_var = self.kwargs['filter_val']
        search_unit = re.split('[\+]', unit_var)
        q = Q()
        for s_unit in search_unit:
            q |= Q(slug__iexact=s_unit)
        units = Unit.objects.filter(q)
        rc_data = Transmission.objects.filter(units__in=units).filter(talkgroup_info__public=True).prefetch_related('units').distinct()
        rc_data = limit_transmission_history(self.request, rc_data)
        restricted, rc_data = restrict_talkgroups(self.request, rc_data)
        return rc_data


class TalkGroupList(ListView):
    model = TalkGroup
    context_object_name = 'talkgroups'
    template_name = 'radio/talkgroup_list.html'

    #queryset = TalkGroup.objects.filter(public=True)
    def get_queryset(self):
        if settings.ACCESS_TG_RESTRICT:
            tg = allowed_tg_list(self.request.user)
        else:
            tg = TalkGroup.objects.filter(public=True)
        return tg



@login_required
@csrf_protect
def upgrade(request):
    if request.method == 'POST':
        form = PaymentForm(request.POST)
        if not form.is_valid():
            return render(
                request,
                'registration/upgrade.html',
                {'form': form},
            )

        try:
            plan = form.cleaned_data.get('plan_type')
            card_name = form.cleaned_data.get('cardholder_name')
            stripe_cust = stripe_models.Customer.objects.get(user=request.user)
            logger.error('Change plan to {} for customer {} Card Name {}'.format(plan, stripe_cust, card_name))
            stripe_info = stripe_actions.subscriptions.create(customer=stripe_cust, plan=plan, token=request.POST.get('stripeToken'))
        except stripe.InvalidRequestError as e:
            messages.error(request, "Error with stripe {}".format(e))
            logger.error("Error with stripe {}".format(e))
            return render(
                request,
                'registration/upgrade.html',
                {'form': form},
            )
        except stripe.CardError as e:
            messages.error(request, "<b>Error</b> Sorry there was an error with processing your card:<br>{}".format(e))
            logger.error("Error with stripe user card{}".format(e))
            return render(
                request,
                'registration/upgrade.html',
                {'form': form},
            )

        print('------ STRIPE DEBUG -----')
        pprint(stripe_info, sys.stderr)
        return render(
           request,
           'registration/upgrade_complete.html',
        )
    else:
        form = PaymentForm()
        return render(
           request,
           'registration/upgrade.html',
           {'form': form, },
        )


@csrf_protect
def register(request):
    if request.method == 'POST':
        form = RegistrationForm(request.POST)
        if form.is_valid():
            user = User.objects.create_user(
            username=form.cleaned_data['username'],
            password=form.cleaned_data['password1'],
            email=form.cleaned_data['email']
            )
            username = form.cleaned_data['username']
            password = form.cleaned_data['password1']
            new_user = authenticate(username=username, password=password)
            if new_user is not None:
                if new_user.is_active:
                    stripe_actions.customers.create(user=new_user)
                    login(request, new_user)
                    return HttpResponseRedirect('/scan/default/')
                else:
                    # this would be weird to get here
                    return HttpResponseRedirect('/register/success/')
            else:
                return HttpResponseRedirect('/register/success/')
    else:
        form = RegistrationForm()
 
    return render(
    request,
    'registration/register.html',
    { 'form': form },
    )

def register_success(request):
    return render(
    request,
    'registration/success.html', {},
    )


class MenuScanListViewSet(viewsets.ModelViewSet):
    serializer_class = MenuScanListSerializer
    queryset = MenuScanList.objects.all()


class MenuTalkGroupListViewSet(viewsets.ModelViewSet):
    serializer_class = MenuTalkGroupListSerializer
    queryset = MenuTalkGroupList.objects.all()


class UnitUpdateView(PermissionRequiredMixin, UpdateView):
    model = Unit
    form_class = UnitEditForm
    success_url = '/unitupdategood/'
    permission_required = ('radio.change_unit')


def ScanDetailsList(request, name):
    template = 'radio/scandetaillist.html'
    scanlist = None
    try:
        scanlist = ScanList.objects.get(name=name)
    except ScanList.DoesNotExist:
        if name == 'default':
            query_data = TalkGroup.objects.all()
        else:
            raise Http404
    if scanlist:
        query_data = scanlist.talkgroups.all()
    return render_to_response(template, {'object_list': query_data, 'scanlist': scanlist, 'request': request})

@login_required
@csrf_protect
def plans(request):
    token = None
    has_verified_email = False
    plans = None
    if request.method == 'POST':
        template = 'radio/subscribed.html'
        token = request.POST.get('stripeToken')
        plan = request.POST.get('plan')
        # See if this user already has a stripe account
        try:
            stripe_cust = stripe_models.Customer.objects.get(user=request.user)
        except ObjectDoesNotExist:
            stripe_actions.customers.create(user=request.user)
            stripe_cust = stripe_models.Customer.objects.get(user=request.user)
        stripe_info = stripe_actions.subscriptions.create(customer=stripe_cust, plan=plan, token=request.POST.get('stripeToken'))
        for t in request.POST:
          logger.error("{} {}".format(t, request.POST[t]))
    else:
        template = 'radio/plans.html'
        plans = StripePlanMatrix.objects.filter(order__lt=99).filter(active=True)

        # Check if users email address is verified
        verified_email = allauth_emailaddress.objects.filter(user=request.user, primary=True, verified=True)
        if verified_email:
            has_verified_email = True


    return render(request, template, {'token': token, 'verified_email': has_verified_email, 'plans': plans} )
