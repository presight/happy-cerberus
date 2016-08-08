#!/usr/bin/python
# -*- coding: utf-8 -*-

import openface
import cv2
import uuid
import os
import random
import pickle
import pdb
import dlib
import time

import numpy as np
np.set_printoptions(precision=2)


class Face:
    def __init__(self, box, rep):
        self.box = box
        self.rep = rep


class Person:
    def __init__(self, name, face, confidence):
        self.name = name
        self.face = face
        self.confidence = confidence


# Return the percentage two squares intersect each other
# from http://stackoverflow.com/questions/9324339/how-much-do-two-rectangles-overlap
def squares_intersect(s1, s2):
    s1x1 = s1.left()
    s1y1 = s1.top()
    s1x2 = s1x1 + s1.height()
    s1y2 = s1y1 + s1.width()
    s2x1 = s2.left()
    s2y1 = s2.top()
    s2x2 = s2x1 + s2.height()
    s2y2 = s2y1 + s2.width()

    si = max(0, max(s1x2, s2x2) - min(s1x1, s2x1)) * max(0, max(s1y2, s2y2) - min(s1y1, s2y1))
    su = s1.width() * s1.height() + s2.width() * s2.height() - si

    return si / su


# Use dlib to remove false positives from face boxes generated by opencv
def is_false_positive(img, box):
    box = cv2_rect_to_dlib(box)
    shape = np.shape(img)
    x1 = box.left()
    y1 = box.top()
    x2 = min(x1 + box.width(), shape[1])
    y2 = min(y1 + box.height(), shape[0])

    faces = align.getAllFaceBoundingBoxes(img)

    return len(faces) == 0


def cv2_rect_to_dlib(rect):
    x1 = long(rect[0])
    y1 = long(rect[1])
    x2 = long(rect[2]) + x1
    y2 = long(rect[3]) + y1
    
    return dlib.rectangle(x1, y1, x2, y2)


# Face detection using opencv. Give some false positives, but is very fast.
def get_faces_bounding_boxes_cv(img):
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    face_boxes = face_cascade.detectMultiScale(
        gray, 
        cv_face_box_scale_factor, 
        cv_face_box_min_neighbours, 
        cv2.cv.CV_HAAR_DO_CANNY_PRUNING, 
        minSize=cv_face_box_min_size
    )

    boxes = []

    for box in face_boxes:
        if not is_false_positive(img, box):
            boxes.append(cv2_rect_to_dlib(box))
            print("Found face %s" % (box))
        else:
            print("Found false positive %s" % (box))

    return boxes


# Face detection using dlib. Accurate but slow.
def get_faces_bounding_boxes_dlib(img):
    # Convert from dlib.rectangles to list
    return [x for x in align.getAllFaceBoundingBoxes(img)]


# Returns a user with its face box intersecting box above the given threshold 
def get_tracked_person(box):
    for person in tracked_persons:
        if squares_intersect(person.face.box, box) > face_intersect_threshold:
            return person

    return None
 

def getFaces(boxes, img):
    faces = []

    for box in boxes:
        tracked_person = get_tracked_person(box)

        # Only do face detection on faces which aren't already tracked
        if not tracked_person:
            aligned_face = align.align(96, img, box, landmarkIndices=openface.AlignDlib.OUTER_EYES_AND_NOSE)
            rep = net.forward(aligned_face)
            faces.append(Face(box, rep))
        else:
            # Update the face box on the tracked face
            tracked_person.face.box = box

    return faces


# Play a welcome message
def optionally_play_message(person):
    if not person.name in played_welcome_messages:
        played_welcome_messages[person.name] = 0

    if played_welcome_messages[person.name] + welcome_message_sleep_time < time.time():
        message = random.choice(available_welcome_messages) % (person.name)
        os.system(text_to_speach_command % (message.replace(' ', '%20')))
        played_welcome_messages[person.name] = time.time()


def findPersons(faces, labels, classifier, img):
    global generated_image_id
    persons = []
    confidences = []
    
    for i, face in enumerate(faces):
        try:
            rep = face.rep.reshape(1, -1)
        except:
            # No Face detected
            return (None, None, None)

        predictions = classifier.predict_proba(rep).ravel()
        max_i = np.argmax(predictions)
        
        name = labels.inverse_transform(max_i)
        confidence = predictions[max_i]

        if confidence > person_confidence_threshold:
            person = Person(name, face, confidence)
            persons.append(person)
            print("Added %s with confidence %s" % (name, confidence))

            optionally_play_message(person)
        else:
            print("Ignored %s with confidence %s" % (name, confidence))

            if save_unknown_faces:
                if not os.path.exists('./generated/unknown'):
                    os.makedirs('./generated/unknown')
                
                aligned_face = align.align(96, img, face.box, landmarkIndices=openface.AlignDlib.OUTER_EYES_AND_NOSE)
                unknown_file = './generated/unknown/%s-%s.png' % (session_id, generated_image_id)
                cv2.imwrite(unknown_file, aligned_face)
                print("Saved unknown image %s" % (unknown_file))

                generated_image_id += 1
        
    return persons


def draw_person_box(img, person):
    box = person.face.box
    x1 = int(box.left())
    y1 = int(box.top())
    x2 = int(box.right())
    y2 = int(box.bottom())
    cv2.rectangle(img, (x1, y1), (x2, y2), (0, 255, 0), 2)

    ts, _ = cv2.getTextSize(person.name, cv2.FONT_HERSHEY_SIMPLEX, 0.8, 1)
    cv2.putText(img, person.name, (x1 - ts[0]/2 + (x2-x1)/2, y1), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255,0,0), 1)


# Match persons and face boxes, remove persons with no corresponding face box
def prune_match_boxes_persons(boxes, persons):
    pruned_boxes = boxes[:]
    pruned_persons = []

    for person in persons:
        for i, box in enumerate(boxes):
            intersect = squares_intersect(person.face.box, box)
            print("%s with %s intersecting %s - %.2f" % (person.name, person.face.box, box, intersect))
            if intersect > face_intersect_threshold:
                person.face.box = box
                pruned_persons.append(person)
                pruned_boxes[i] = None

    pruned_boxes = [box for box in pruned_boxes if box is not None]

    return (pruned_boxes, pruned_persons)


if __name__ == '__main__':
    face_detector = get_faces_bounding_boxes_dlib
    face_intersect_threshold = 0.9
    person_confidence_threshold = 0.99
    image_size = (640//2,480//2)
    update_faces_skip_frames = 3
    
    show_video = True
    video_capture_device = 0

    facePredictorFile = './openface/models/dlib/shape_predictor_68_face_landmarks.dat'
    torchNetworkModelFile = './openface/models/openface/nn4.small2.v1.t7'
    face_image_dim = 96
    classifierFile = './generated/classifier.pkl'
    
    face_cascade = cv2.CascadeClassifier('/usr/share/opencv/haarcascades/haarcascade_frontalface_default.xml')
    cv_face_box_min_size = (25, 25)
    cv_face_box_scale_factor = 1.1
    cv_face_box_min_neighbours = 3
    
    # Save aligned images of all faces detected but not identified with a label
    save_unknown_faces = True
    session_id = str(uuid.uuid1())
    generated_image_id = 0

    welcome_message_sleep_time = 60
    played_welcome_messages = {}
    available_welcome_messages = [
        'Hello %s, how are you today?',
        'Oh, is it you again %s?',
        'Hi there %s! You\'re awesome and you know it.',
        "%s, is it you?",
        "All rise for %s!"
    ]

    #text_to_speach_command = 'espeak "%s"&'
    text_to_speach_command = 'curl "http://localhost:59125/process?INPUT_TYPE=TEXT&AUDIO=WAVE_FILE&OUTPUT_TYPE=AUDIO&LOCALE=EN_US&INPUT_TEXT=%s"|aplay&'

    tracked_persons = []
    align = openface.AlignDlib(facePredictorFile)
    net = openface.TorchNeuralNet(torchNetworkModelFile, imgDim=face_image_dim)
    iteration = 0
     
    vc = cv2.VideoCapture(video_capture_device)

    with open(classifierFile, 'r') as f:
        (labels, classifier) = pickle.load(f)

    while True:
        _, img = vc.read()
        img = cv2.resize(img, image_size, interpolation = cv2.INTER_CUBIC)

        # Skip frames to avoid these expensive steps
        if iteration % update_faces_skip_frames == 0:
            boxes = face_detector(img)
            boxes, pruned_tracked_persons = prune_match_boxes_persons(boxes, tracked_persons)
 
            faces = getFaces(boxes, img)
            tracked_persons = findPersons(faces, labels, classifier, img) + pruned_tracked_persons

        for person in tracked_persons:
            if show_video:
                draw_person_box(img, person)
            
            print("Tracking %s in %s" % (person.name, person.face.box))

        if show_video:
            cv2.imshow('Video', img)

            if cv2.waitKey(1) & 0xFF == ord('q'):
                break

        iteration += 1

    vc.release()
    cv2.destroyAllWindows()
