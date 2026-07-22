"""
HTTP concerns only: routing to a service call, permission checks, and
response status codes. No business logic here (Design Spec Sec 3.1).
"""

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from . import serializers, services


class JudgingRoundListCreateView(APIView):
    """GET /judging/rounds -- FR-JUDGE-004. Lists the judging rounds for a
    hackathon (optionally scoped to a track), visible to the hackathon's
    Organizer and, for track-scoped rounds, that track's Sponsor
    (services.list_rounds). POST creates a round: track=None creates the
    Overall round (Organizer only); a trackId creates that track's round
    (Organizer or the track's Sponsor)."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: serializers.JudgingRoundSerializer(many=True)})
    def get(self, request):
        hackathon_id = request.query_params.get("hackathonId")
        if not hackathon_id:
            return Response({"hackathonId": ["This query parameter is required."]}, status=400)
        rounds = services.list_rounds(
            actor=request.user,
            hackathon_id=hackathon_id,
            track_id=request.query_params.get("trackId"),
        )
        return Response(serializers.JudgingRoundSerializer(rounds, many=True).data)

    @extend_schema(
        request=serializers.JudgingRoundCreateSerializer,
        responses={201: serializers.JudgingRoundSerializer},
    )
    def post(self, request):
        serializer = serializers.JudgingRoundCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        round = services.create_round(actor=request.user, **serializer.validated_data)
        return Response(serializers.JudgingRoundSerializer(round).data, status=status.HTTP_201_CREATED)


class JudgingCriterionListCreateView(APIView):
    """GET/POST /judging/rounds/{round_id}/criteria -- FR-HACK-004 / BR-005.
    Rubric management for a round; restricted to that round's manager
    (Organizer, or the track's Sponsor for a track-scoped round). Criteria
    cannot be added once the round has opened (services.create_criterion)."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: serializers.JudgingCriterionSerializer(many=True)})
    def get(self, request, round_id):
        criteria = services.list_criteria(actor=request.user, round_id=round_id)
        return Response(serializers.JudgingCriterionSerializer(criteria, many=True).data)

    @extend_schema(
        request=serializers.JudgingCriterionCreateSerializer,
        responses={201: serializers.JudgingCriterionSerializer},
    )
    def post(self, request, round_id):
        serializer = serializers.JudgingCriterionCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        criterion = services.create_criterion(
            actor=request.user, round_id=round_id, **serializer.validated_data,
        )
        return Response(serializers.JudgingCriterionSerializer(criterion).data, status=status.HTTP_201_CREATED)


class JudgeInvitationCreateView(APIView):
    """POST /judging/judge/invitations -- FR-JUDGE-001. Invites an email
    address to judge a round; restricted to that round's manager, and only
    while the round is not_started (services.invite_judge)."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=serializers.JudgeInvitationCreateSerializer,
        responses={201: serializers.JudgeInvitationSerializer},
    )
    def post(self, request):
        serializer = serializers.JudgeInvitationCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        invitation = services.invite_judge(actor=request.user, **serializer.validated_data)
        return Response(serializers.JudgeInvitationSerializer(invitation).data, status=status.HTTP_201_CREATED)


class JudgeInvitationAcceptView(APIView):
    """POST /judging/judge/invitations/{invitation_id}/accept -- FR-JUDGE-001.
    Accepted only by the invited email's own account; grants that account
    a judge RoleAssignment on the hackathon (services.accept_invitation)."""

    permission_classes = [IsAuthenticated]

    @extend_schema(request=None, responses={200: serializers.JudgeInvitationSerializer})
    def post(self, request, invitation_id):
        invitation = services.accept_invitation(actor=request.user, invitation_id=invitation_id)
        return Response(serializers.JudgeInvitationSerializer(invitation).data)


class AssignmentListCreateView(APIView):
    """GET/POST /judging/rounds/{round_id}/assignments -- FR-JUDGE-001. GET
    is available to the round's manager for any judge, and to a judge for
    their own assignments only (pass judgeUserId equal to your own id --
    services.list_assignments). POST manually assigns one submission to one
    judge; Organizer only, and only before the round opens."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: serializers.AssignmentSerializer(many=True)})
    def get(self, request, round_id):
        assignments = services.list_assignments(
            actor=request.user,
            round_id=round_id,
            judge_user_id=request.query_params.get("judgeUserId"),
        )
        return Response(serializers.AssignmentSerializer(assignments, many=True).data)

    @extend_schema(
        request=serializers.AssignmentCreateSerializer,
        responses={201: serializers.AssignmentSerializer},
    )
    def post(self, request, round_id):
        serializer = serializers.AssignmentCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        assignment = services.assign_judge(
            actor=request.user, round_id=round_id, **serializer.validated_data,
        )
        return Response(serializers.AssignmentSerializer(assignment).data, status=status.HTTP_201_CREATED)


class AssignmentDeleteView(APIView):
    """DELETE /judging/assignments/{assignment_id} -- FR-JUDGE-001. Organizer
    only, and only before the round opens. If the judge already scored the
    submission, the caller must resend with confirmScoreDiscard to also
    delete those scores (services.remove_assignment)."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=serializers.AssignmentChangeSerializer,
        responses={204: None},
    )
    def delete(self, request, assignment_id):
        serializer = serializers.AssignmentChangeSerializer(data=request.data or {})
        serializer.is_valid(raise_exception=True)
        services.remove_assignment(
            actor=request.user,
            assignment_id=assignment_id,
            **serializer.validated_data,
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


class AssignmentReassignView(APIView):
    """POST /judging/assignments/{assignment_id}/reassign -- FR-JUDGE-001.
    Swaps the assigned judge for one who has already accepted an invitation
    to the round; Organizer only, and only before the round opens. Requires
    confirmScoreDiscard if the outgoing judge already scored the submission
    (services.reassign_judge)."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=serializers.AssignmentReassignSerializer,
        responses={200: serializers.AssignmentSerializer},
    )
    def post(self, request, assignment_id):
        serializer = serializers.AssignmentReassignSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        assignment = services.reassign_judge(
            actor=request.user,
            assignment_id=assignment_id,
            **serializer.validated_data,
        )
        return Response(serializers.AssignmentSerializer(assignment).data)


class AutoDistributionView(APIView):
    """POST /judging/rounds/{round_id}/assignments/auto -- FR-JUDGE-001.
    Round-robin assigns every eligible submission in the round's scope
    across the given judges (each of whom must already have accepted an
    invitation to the round); Organizer only, and only before the round
    opens (services.auto_distribute)."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=serializers.AutoDistributionSerializer,
        responses={201: serializers.AssignmentSerializer(many=True)},
    )
    def post(self, request, round_id):
        serializer = serializers.AutoDistributionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        assignments = services.auto_distribute(
            actor=request.user, round_id=round_id, **serializer.validated_data,
        )
        return Response(serializers.AssignmentSerializer(assignments, many=True).data, status=status.HTTP_201_CREATED)


class SubmissionScoreListView(APIView):
    """GET /judging/submissions/{submission_id}/scores -- FR-JUDGE-002.
    Every judge's per-criterion scores for a submission; restricted to the
    hackathon's Organizer (services.list_submission_scores)."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: serializers.ScoreSerializer(many=True)})
    def get(self, request, submission_id):
        scores = services.list_submission_scores(actor=request.user, submission_id=submission_id)
        return Response(serializers.ScoreSerializer(scores, many=True).data)


class SubmissionScoreCreateView(APIView):
    """POST /judging/submissions/{submission_id}/score -- FR-JUDGE-002.
    Saves or updates the caller's own score for one criterion on a
    submission they are assigned to judge. Scores can be saved as draft or
    final while the round is open; a final score becomes immutable to the
    judge once saved (services.submit_score)."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=serializers.ScoreCreateSerializer,
        responses={201: serializers.ScoreSerializer},
    )
    def post(self, request, submission_id):
        serializer = serializers.ScoreCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        score = services.submit_score(
            actor=request.user, submission_id=submission_id, **serializer.validated_data,
        )
        return Response(serializers.ScoreSerializer(score).data, status=status.HTTP_201_CREATED)


class ScoreReopenView(APIView):
    """POST /judging/scores/{score_id}/reopen -- FR-JUDGE-002. Reverts a
    final score back to draft so the judge can revise it, recording an
    audit log entry; Organizer only, and requires a reason of at least 10
    characters (services.reopen_score)."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=serializers.ScoreReopenSerializer,
        responses={200: serializers.ScoreSerializer},
    )
    def post(self, request, score_id):
        serializer = serializers.ScoreReopenSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        score = services.reopen_score(
            actor=request.user, score_id=score_id, **serializer.validated_data,
        )
        return Response(serializers.ScoreSerializer(score).data)


class RoundResultListView(APIView):
    """GET /judging/rounds/{round_id}/results -- FR-JUDGE-003. The
    materialized, rank-ordered aggregate scores for a closed round;
    restricted to that round's manager."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: serializers.RoundResultSerializer(many=True)})
    def get(self, request, round_id):
        round = services._get_round_or_404(round_id)
        services._require_round_manager(actor=request.user, round=round)
        results = round.results.all().order_by("rank")
        return Response(serializers.RoundResultSerializer(results, many=True).data)


class RoundOpenView(APIView):
    """POST /judging/rounds/{round_id}/open -- FR-JUDGE-004. Moves a
    not_started round to open, after validating the rubric's criterion
    weights sum to 100; restricted to that round's manager
    (services.open_round)."""

    permission_classes = [IsAuthenticated]

    @extend_schema(request=None, responses={200: serializers.JudgingRoundSerializer})
    def post(self, request, round_id):
        round = services.open_round(actor=request.user, round_id=round_id)
        return Response(serializers.JudgingRoundSerializer(round).data)


class RoundCloseView(APIView):
    """POST /judging/rounds/{round_id}/close -- FR-JUDGE-004. Moves an open
    round to closed and materializes its RoundResult rows; restricted to
    that round's manager (services.close_round -> services.calculate_round_results)."""

    permission_classes = [IsAuthenticated]

    @extend_schema(request=None, responses={200: serializers.JudgingRoundSerializer})
    def post(self, request, round_id):
        round = services.close_round(actor=request.user, round_id=round_id)
        return Response(serializers.JudgingRoundSerializer(round).data)