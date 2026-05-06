from django.shortcuts import render
from .utils import *
from django.http import StreamingHttpResponse
from django.shortcuts import render
from django.http import HttpResponse


def demorecognition(request):
    return render(request, 'demorecognition.html', {})

